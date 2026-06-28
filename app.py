"""
AU Chatbot — Web Server
Serves a beautiful chat UI and exposes the RAG agent via REST API.
Includes authentication, email OTP, role-based access, and document management.
"""

import os
import re
import time
import sqlite3
import secrets
import smtplib
import bcrypt
import jwt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict, Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv
import aiosmtplib

load_dotenv()


# ── Database Setup (SQLite) ──────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            username TEXT,
            password_hash TEXT,
            role TEXT DEFAULT 'user',
            verified INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            code TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# ── Authentication config ────────────────────────────────────────────────────

JWT_SECRET = os.environ.get("JWT_SECRET", "fallback_secret_key_12345")
JWT_ALGORITHM = "HS256"
ADMIN_EMAIL = "golthitharunkumar@gmail.com"
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


# ── Auth Helpers ─────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def get_current_user(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    c = db.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
        
    return dict(user)

def get_current_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not authorized (Admin only)")
    return user


async def send_otp_email(to_email: str, code: str):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"WARNING: SMTP credentials missing. Fake sending OTP {code} to {to_email}")
        return
        
    message = MIMEMultipart("alternative")
    message["Subject"] = "AU Chatbot - Verification Code"
    message["From"] = f"AU Chatbot <{SMTP_EMAIL}>"
    message["To"] = to_email

    html = f"""
    <html>
      <body>
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 10px;">
            <h2 style="color: #1a237e; text-align: center;">Aditya University Chatbot</h2>
            <p>Hello,</p>
            <p>Your verification code is:</p>
            <div style="text-align: center; margin: 30px 0;">
                <span style="font-size: 32px; font-weight: bold; letter-spacing: 5px; background: #f5f5f5; padding: 15px 30px; border-radius: 8px; color: #333;">{code}</span>
            </div>
            <p>This code will expire in 5 minutes.</p>
            <p>If you didn't request this, you can safely ignore this email.</p>
        </div>
      </body>
    </html>
    """
    message.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            message,
            hostname="smtp.gmail.com",
            port=465,
            use_tls=True,
            username=SMTP_EMAIL,
            password=SMTP_PASSWORD,
            timeout=15.0
        )
        print(f"OTP email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise Exception(f"SMTP failed: {str(e)}")


# ── Agent State ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    question: str
    rewritten_question: str
    documents: list[str]
    answer: str
    grade: str
    retry_count: int


# ── Initialize LLM and Vector Store ─────────────────────────────────────────

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.environ.get("GROQ_API_KEY")
)

DOCS_FOLDER = Path(__file__).parent / "docs"
DOCS_FOLDER.mkdir(exist_ok=True)

STATIC_FOLDER = Path(__file__).parent / "static"
KB_IMAGES_FOLDER = STATIC_FOLDER / "kb_images"
KB_IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)

chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(
    name="knowledge_base",
    metadata={"hnsw:space": "cosine"}
)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=50,
)


# ── Ingestion Helper ────────────────────────────────────────────────────────

def ingest_single_file(file_path: Path) -> int:
    """Read a single .txt file, chunk it, and add to ChromaDB. Returns chunk count."""
    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        return 0

    from langchain_core.documents import Document
    doc = Document(page_content=content, metadata={"source": str(file_path)})
    chunks = text_splitter.split_documents([doc])

    if not chunks:
        return 0

    # Use source-prefixed IDs so we can delete by source later
    source_key = file_path.name
    existing = collection.get(where={"source": str(file_path)})
    existing_count = len(existing["ids"]) if existing and existing["ids"] else 0

    # Generate unique IDs using timestamp to avoid collisions
    ts = int(time.time() * 1000)
    documents = [c.page_content for c in chunks]
    ids = [f"{source_key}_{ts}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": str(file_path)} for _ in chunks]

    collection.add(documents=documents, ids=ids, metadatas=metadatas)
    return len(chunks)


# ── Graph Nodes ──────────────────────────────────────────────────────────────

def retrieve(state: AgentState) -> AgentState:
    """Search ChromaDB for documents relevant to the current question."""
    question = state.get("rewritten_question") or state["question"]
    try:
        results = collection.query(query_texts=[question], n_results=3)
        documents = results["documents"][0] if results["documents"] else []
    except Exception:
        documents = []
    return {**state, "documents": documents}


def generate(state: AgentState) -> AgentState:
    """Generate an answer using the LLM based on retrieved documents."""
    question = state.get("rewritten_question") or state["question"]
    documents = state.get("documents", [])

    if not documents:
        return {**state, "answer": "No relevant documents were found."}

    context = "\n\n".join([f"Document {i+1}:\n{doc}"
                           for i, doc in enumerate(documents)])

    system_prompt = """You are a helpful assistant that answers questions about Aditya University
based strictly on the provided documents. If the documents do not contain
enough information to answer the question, say so honestly.
Do not use any knowledge outside of the provided documents."""

    user_prompt = f"""Documents:
{context}

Question: {question}

Answer based only on the documents above:"""

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
        answer = response.content
    except Exception as error:
        answer = f"An error occurred while generating the answer: {error}"

    return {**state, "answer": answer}


def grade_answer(state: AgentState) -> AgentState:
    """Grade whether the answer is grounded in the retrieved documents."""
    answer = state["answer"]
    documents = state.get("documents", [])
    question = state.get("rewritten_question") or state["question"]
    context = "\n".join(documents)

    grade_prompt = f"""You are a grading assistant. Your job is to determine
if an answer is grounded in and supported by the provided documents.

Documents:
{context}

Question: {question}

Answer: {answer}

Is this answer grounded in the documents? Reply with ONLY "pass" or "fail"."""

    try:
        response = llm.invoke([HumanMessage(content=grade_prompt)])
        grade = response.content.strip().lower()
        grade = "pass" if "pass" in grade else "fail"
    except Exception:
        grade = "fail"

    return {**state, "grade": grade}


def rewrite_question(state: AgentState) -> AgentState:
    """Rephrase the question for a better retrieval attempt."""
    question = state.get("rewritten_question") or state["question"]
    retry_count = state.get("retry_count", 0)

    rewrite_prompt = f"""You are a question rewriter. Your goal is to rephrase
the following question to get better search results from a document database.

Original question: {question}

Rewrite the question to be clearer and more specific.
Return ONLY the rewritten question, nothing else."""

    try:
        response = llm.invoke([HumanMessage(content=rewrite_prompt)])
        new_question = response.content.strip()
    except Exception:
        new_question = question

    return {**state, "rewritten_question": new_question, "retry_count": retry_count + 1}


def give_up(state: AgentState) -> AgentState:
    """Return an honest 'I don't know' when max retries are exceeded."""
    return {
        **state,
        "answer": "I don't know. The system could not find a well-supported "
                   "answer after multiple attempts."
    }


def route_after_grade(state: AgentState) -> str:
    """Decide next step after grading the answer."""
    if state["grade"] == "pass":
        return END
    if state.get("retry_count", 0) >= 2:
        return "give_up"
    return "rewrite_question"


# ── Build the Graph ──────────────────────────────────────────────────────────

workflow = StateGraph(AgentState)
workflow.add_node("retrieve", retrieve)
workflow.add_node("generate", generate)
workflow.add_node("grade_answer", grade_answer)
workflow.add_node("rewrite_question", rewrite_question)
workflow.add_node("give_up", give_up)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", "grade_answer")
workflow.add_conditional_edges(
    "grade_answer", route_after_grade,
    {END: END, "rewrite_question": "rewrite_question", "give_up": "give_up"}
)
workflow.add_edge("rewrite_question", "retrieve")
workflow.add_edge("give_up", END)

app_graph = workflow.compile()


# ── FastAPI Web Server ───────────────────────────────────────────────────────

app = FastAPI(title="AU Chatbot System")

# Serve static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main UI (handles Auth and Chat)."""
    html_file = static_path / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


# ── Auth Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/auth/register")
async def register(request: Request, db: sqlite3.Connection = Depends(get_db)):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not email or not username or not password:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    c = db.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    if c.fetchone():
        return JSONResponse({"error": "Email already registered"}, status_code=400)

    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    role = "admin" if email == ADMIN_EMAIL else "user"

    c.execute(
        "INSERT INTO users (email, username, password_hash, role, verified, created_at) VALUES (?, ?, ?, ?, 1, ?)",
        (email, username, hashed_pw.decode('utf-8'), role, datetime.utcnow().isoformat())
    )
    db.commit()

    return {"message": "Registration successful. You can now login."}


@app.post("/api/auth/verify-otp")
async def verify_otp(request: Request, db: sqlite3.Connection = Depends(get_db)):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    if not email or not code:
        return JSONResponse({"error": "Missing email or code"}, status_code=400)

    c = db.cursor()
    c.execute("SELECT * FROM otp_codes WHERE email = ? AND code = ?", (email, code))
    otp_record = c.fetchone()

    if not otp_record:
        return JSONResponse({"error": "Invalid OTP code"}, status_code=400)

    expires_at = datetime.fromisoformat(otp_record["expires_at"])
    if datetime.utcnow() > expires_at:
        return JSONResponse({"error": "OTP code has expired"}, status_code=400)

    # Valid OTP -> Verify user
    c.execute("UPDATE users SET verified = 1 WHERE email = ?", (email,))
    c.execute("DELETE FROM otp_codes WHERE email = ?", (email,))
    db.commit()

    return {"message": "Account verified successfully. You can now login."}


@app.post("/api/auth/login")
async def login(request: Request, response: Response, db: sqlite3.Connection = Depends(get_db)):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return JSONResponse({"error": "Missing email or password"}, status_code=400)

    c = db.cursor()
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()

    if not user or not bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    access_token = create_access_token(data={"sub": user["email"]})
    
    response = JSONResponse({
        "message": "Login successful",
        "user": {
            "email": user["email"],
            "username": user["username"],
            "role": user["role"]
        }
    })
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,  # 7 days
        samesite="lax",
        secure=False # Set to True in prod with HTTPS
    )
    return response


@app.get("/api/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {
        "email": user["email"],
        "username": user["username"],
        "role": user["role"]
    }


@app.post("/api/auth/logout")
async def logout():
    response = JSONResponse({"message": "Logout successful"})
    response.delete_cookie("access_token")
    return response


@app.post("/api/auth/forgot-password")
async def forgot_password(request: Request, db: sqlite3.Connection = Depends(get_db)):
    data = await request.json()
    email = data.get("email", "").strip().lower()

    if not email:
        return JSONResponse({"error": "Missing email"}, status_code=400)

    c = db.cursor()
    c.execute("SELECT * FROM users WHERE email = ? AND verified = 1", (email,))
    user = c.fetchone()

    if not user:
        return JSONResponse({"error": "Account not found or not verified"}, status_code=404)

    # Generate OTP
    code = f"{secrets.randbelow(1000000):06d}"
    expires = datetime.utcnow() + timedelta(minutes=5)
    
    c.execute("DELETE FROM otp_codes WHERE email = ?", (email,))
    c.execute(
        "INSERT INTO otp_codes (email, code, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (email, code, datetime.utcnow().isoformat(), expires.isoformat())
    )
    db.commit()

    try:
        await send_otp_email(email, code)
    except Exception as e:
        error_msg = str(e)
        return JSONResponse({"error": f"Email failed: {error_msg}"}, status_code=500)

    return {"message": "OTP sent to email", "email": email}


@app.post("/api/auth/reset-password")
async def reset_password(request: Request, db: sqlite3.Connection = Depends(get_db)):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    new_password = data.get("new_password", "")

    if not email or not code or not new_password:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    c = db.cursor()
    c.execute("SELECT * FROM otp_codes WHERE email = ? AND code = ?", (email, code))
    otp_record = c.fetchone()

    if not otp_record:
        return JSONResponse({"error": "Invalid or expired OTP"}, status_code=400)

    expires_at = datetime.fromisoformat(otp_record["expires_at"])
    if datetime.utcnow() > expires_at:
        c.execute("DELETE FROM otp_codes WHERE email = ?", (email,))
        db.commit()
        return JSONResponse({"error": "OTP has expired. Please request a new one."}, status_code=400)

    # Hash new password
    hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())

    # Update password
    c.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?",
        (hashed_pw.decode('utf-8'), email)
    )
    
    # Delete OTP
    c.execute("DELETE FROM otp_codes WHERE email = ?", (email,))
    db.commit()

    return {"message": "Password updated successfully"}


# ── Protected Chat Endpoints ──────────────────────────────────────────────────

@app.post("/ask")
async def ask_question_endpoint(request: Request, user: dict = Depends(get_current_user)):
    """Process a question through the self-healing RAG pipeline."""
    data = await request.json()
    question = data.get("question", "").strip()

    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    start_time = time.time()

    result = app_graph.invoke({
        "question": question,
        "rewritten_question": "",
        "documents": [],
        "answer": "",
        "grade": "",
        "retry_count": 0,
    })

    elapsed = round(time.time() - start_time, 2)

    return JSONResponse({
        "answer": result["answer"],
        "grade": result["grade"],
        "retry_count": result.get("retry_count", 0),
        "documents_found": len(result.get("documents", [])),
        "rewritten_question": result.get("rewritten_question", ""),
        "time_taken": elapsed,
    })


@app.get("/stats")
async def get_stats():
    """Get knowledge base statistics."""
    try:
        count = collection.count()
    except Exception:
        count = 0
    return JSONResponse({
        "total_chunks": count,
        "collection_name": "knowledge_base",
        "model": "llama-3.3-70b-versatile",
    })


# ── Protected Document Management API (Admin Only) ──────────────────────────

@app.get("/api/documents")
async def list_documents(admin: dict = Depends(get_current_admin)):
    """List all documents in the knowledge base with their chunk counts."""
    docs = []
    for f in sorted(DOCS_FOLDER.glob("*.txt")):
        # Count chunks belonging to this file in ChromaDB
        try:
            results = collection.get(where={"source": str(f)})
            chunk_count = len(results["ids"]) if results and results["ids"] else 0
        except Exception:
            chunk_count = 0
        docs.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "chunk_count": chunk_count,
        })
    return JSONResponse({"documents": docs})


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...), 
    description: str = Form(None), 
    admin: dict = Depends(get_current_admin)
):
    """Upload a file to the knowledge base (.txt or image)."""
    filename = file.filename.lower()
    is_image = filename.endswith((".jpg", ".jpeg", ".png"))
    is_txt = filename.endswith(".txt")
    
    if not (is_txt or is_image):
        return JSONResponse({"error": "Only .txt, .jpg, and .png files are supported."}, status_code=400)

    # Sanitize filename
    safe_name = re.sub(r'[^\w\-. ]', '_', file.filename)
    
    if is_image:
        if not description or not description.strip():
            return JSONResponse({"error": "A description is required for images."}, status_code=400)
            
        img_dest = KB_IMAGES_FOLDER / safe_name
        content = await file.read()
        img_dest.write_bytes(content)
        
        # Create a proxy text file for the AI to read
        proxy_filename = safe_name + ".txt"
        dest = DOCS_FOLDER / proxy_filename
        
        # Give the AI explicit instructions on how to show the image
        text = f"Image of {description}. If the user asks to see this, or asks for photos related to this, show this image using exactly this markdown: ![{description}](/static/kb_images/{safe_name})"
        dest.write_text(text, encoding="utf-8")
        
    else:
        dest = DOCS_FOLDER / safe_name
        content = await file.read()
        text = content.decode("utf-8", errors="replace")
        if not text.strip():
            return JSONResponse({"error": "File is empty."}, status_code=400)
        dest.write_text(text, encoding="utf-8")

    chunks_added = ingest_single_file(dest)

    return JSONResponse({
        "message": f"Uploaded '{safe_name}' successfully.",
        "filename": safe_name,
        "chunks_added": chunks_added,
    })


@app.post("/api/documents/text")
async def add_text_document(request: Request, admin: dict = Depends(get_current_admin)):
    """Add raw text content as a new document in the knowledge base."""
    data = await request.json()
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()

    if not title:
        return JSONResponse({"error": "Please provide a title."}, status_code=400)
    if not content:
        return JSONResponse({"error": "Please provide content."}, status_code=400)

    # Create a safe filename
    safe_name = re.sub(r'[^\w\-. ]', '_', title)
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"

    dest = DOCS_FOLDER / safe_name
    dest.write_text(content, encoding="utf-8")

    chunks_added = ingest_single_file(dest)

    return JSONResponse({
        "message": f"Created '{safe_name}' successfully.",
        "filename": safe_name,
        "chunks_added": chunks_added,
    })


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str, admin: dict = Depends(get_current_admin)):
    """Delete a document from both disk and ChromaDB."""
    file_path = DOCS_FOLDER / filename

    if not file_path.exists():
        return JSONResponse({"error": "File not found."}, status_code=404)

    # Delete from ChromaDB
    try:
        results = collection.get(where={"source": str(file_path)})
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            deleted_chunks = len(results["ids"])
        else:
            deleted_chunks = 0
    except Exception:
        deleted_chunks = 0

    # Delete from disk
    file_path.unlink()

    return JSONResponse({
        "message": f"Deleted '{filename}' successfully.",
        "chunks_removed": deleted_chunks,
    })


if __name__ == "__main__":
    import uvicorn
    print("\n[*] AU Chatbot System")
    print("=" * 45)
    print("Open in browser: http://localhost:8000")
    print("=" * 45)
    uvicorn.run(app, host="0.0.0.0", port=8000)
