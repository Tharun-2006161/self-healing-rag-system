// ─── AU Chatbot — Frontend Logic ──────────────────────────────

document.addEventListener('DOMContentLoaded', function () {

    // ─── DOM References ─────────────────────────────────────────────────────
    
    // Pages
    const pageLogin = document.getElementById('page-login');
    const pageRegister = document.getElementById('page-register');
    const pageForgotPassword = document.getElementById('page-forgot-password');
    const pageResetPassword = document.getElementById('page-reset-password');
    const pageChat = document.getElementById('page-chat');

    // Forms
    const formLogin = document.getElementById('form-login');
    const formRegister = document.getElementById('form-register');
    const formForgotPassword = document.getElementById('form-forgot-password');
    const formResetPassword = document.getElementById('form-reset-password');

    // Navigation Links
    const linkToLogin = document.getElementById('link-to-login');
    const linkToRegister = document.getElementById('link-to-register');
    const linkToForgotPassword = document.getElementById('link-to-forgot-password');
    const linkBackLoginFromForgot = document.getElementById('link-back-login-from-forgot');
    const linkBackForgot = document.getElementById('link-back-forgot');

    // User Info Display
    const navUsername = document.getElementById('nav-username');
    const navRole = document.getElementById('nav-role');
    const welcomeUsername = document.getElementById('welcome-username');
    const btnLogout = document.getElementById('btn-logout');
    
    // Chat & KB Elements
    const messagesContainer = document.getElementById('messages');
    const chatArea = document.getElementById('chat-area');
    const welcomeSection = document.getElementById('welcome-section');
    const inputForm = document.getElementById('input-form');
    const questionInput = document.getElementById('question-input');
    const sendBtn = document.getElementById('send-btn');

    const fab = document.getElementById('fab-kb');
    const kbDrawer = document.getElementById('kb-drawer');
    const kbOverlay = document.getElementById('kb-overlay');
    const kbCloseBtn = document.getElementById('kb-close-btn');
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const kbDocList = document.getElementById('kb-doc-list');
    const addTextBtn = document.getElementById('add-text-btn');

    let isProcessing = false;
    let loadingCounter = 0;
    let currentUser = null;
    let pendingOtpEmail = null;

    // ─── Page Router ────────────────────────────────────────────────────────
    
    function showPage(pageId) {
        document.querySelectorAll('.auth-page, .app-container').forEach(el => {
            el.style.display = 'none';
            el.classList.remove('active');
        });
        
        const target = document.getElementById(pageId);
        if (pageId === 'page-chat') {
            target.style.display = 'flex';
        } else {
            target.style.display = 'flex';
            target.classList.add('active');
        }
    }

    // ─── Auth Flow ──────────────────────────────────────────────────────────

    async function checkAuth() {
        try {
            const res = await fetch('/api/auth/me');
            if (res.ok) {
                currentUser = await res.json();
                setupUserUI();
                showPage('page-chat');
            } else {
                showPage('page-login');
            }
        } catch (err) {
            showPage('page-login');
        }
    }

    function setupUserUI() {
        if (!currentUser) return;
        
        navUsername.textContent = currentUser.username;
        welcomeUsername.textContent = currentUser.username;
        navRole.textContent = currentUser.role;
        
        // Setup Role badge styling
        navRole.className = 'role-tag ' + currentUser.role;
        
        // Show/Hide Manage KB FAB based on role
        if (currentUser.role === 'admin') {
            fab.style.display = 'flex';
        } else {
            fab.style.display = 'none';
            closeDrawer(); // ensure it's closed if they aren't admin
        }
    }

    // Link Handlers
    linkToLogin.addEventListener('click', (e) => { e.preventDefault(); showPage('page-login'); });
    if(linkToRegister) linkToRegister.addEventListener('click', (e) => { e.preventDefault(); showPage('page-register'); });
    linkToForgotPassword.addEventListener('click', (e) => { e.preventDefault(); showPage('page-forgot-password'); });
    linkBackLoginFromForgot.addEventListener('click', (e) => { e.preventDefault(); showPage('page-login'); });
    linkBackForgot.addEventListener('click', (e) => { e.preventDefault(); showPage('page-forgot-password'); });

    // Forgot Password Handler
    formForgotPassword.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('forgot-email').value;
        const btn = formForgotPassword.querySelector('button');
        btn.disabled = true;
        btn.textContent = 'Sending...';

        try {
            const res = await fetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            const data = await res.json();
            
            if (res.ok) {
                pendingOtpEmail = email;
                document.getElementById('reset-email-display').textContent = email;
                showPage('page-reset-password');
                showToast('Reset code sent to your email!', 'success');
            } else {
                showToast(data.error, 'error');
            }
        } catch (err) {
            showToast('Request failed. Check connection.', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Send Reset Code';
        }
    });

    // Reset Password Handler
    formResetPassword.addEventListener('submit', async (e) => {
        e.preventDefault();
        const resetInputs = document.querySelectorAll('.reset-digit');
        const code = Array.from(resetInputs).map(i => i.value).join('');
        const newPassword = document.getElementById('reset-new-password').value;

        if (code.length !== 6) {
            showToast('Please enter all 6 digits', 'error');
            return;
        }

        const btn = formResetPassword.querySelector('button');
        btn.disabled = true;
        btn.textContent = 'Updating...';

        try {
            const res = await fetch('/api/auth/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: pendingOtpEmail, code, new_password: newPassword })
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast('Password updated! You can now login.', 'success');
                showPage('page-login');
                formForgotPassword.reset();
                formResetPassword.reset();
                resetInputs.forEach(i => i.value = '');
            } else {
                showToast(data.error, 'error');
            }
        } catch (err) {
            showToast('Reset failed. Check connection.', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Update Password';
        }
    });



    // Register Handler
    formRegister.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('reg-username').value;
        const password = document.getElementById('reg-password').value;
        const confirmPassword = document.getElementById('reg-confirm-password').value;
        const email = document.getElementById('reg-email').value;
        
        if (password !== confirmPassword) {
            showToast('Passwords do not match', 'error');
            return;
        }

        const btn = formRegister.querySelector('button');
        btn.disabled = true;
        btn.textContent = 'Signing Up...';

        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, username, password })
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast('Account created! Please sign in.', 'success');
                formRegister.reset();
                showPage('page-login');
            } else {
                showToast(data.error, 'error');
            }
        } catch (err) {
            showToast('Registration failed. Check connection.', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Sign Up';
        }
    });

    // OTP Input Logic (For both Registration and Reset Password)
    const setupOtpInputs = (selector) => {
        const inputs = document.querySelectorAll(selector);
        inputs.forEach((input, index) => {
            input.addEventListener('input', (e) => {
                if (e.target.value.length === 1 && index < inputs.length - 1) {
                    inputs[index + 1].focus();
                }
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !e.target.value && index > 0) {
                    inputs[index - 1].focus();
                }
            });
        });
    };

    setupOtpInputs('#form-reset-password .reset-digit');



    // Login Handler
    formLogin.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        
        const btn = formLogin.querySelector('button');
        btn.disabled = true;
        btn.textContent = 'Logging in...';

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            
            if (res.ok) {
                currentUser = data.user;
                setupUserUI();
                showPage('page-chat');
                showToast('Welcome back!', 'success');
                formLogin.reset();
            } else {
                showToast(data.error, 'error');
            }
        } catch (err) {
            showToast('Login failed. Check connection.', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Login';
        }
    });

    // Logout Handler
    btnLogout.addEventListener('click', async () => {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
        } catch(e) {} // ignore errors on logout
        currentUser = null;
        showPage('page-login');
        showToast('Logged out successfully', 'success');
    });

    // Initialize Auth state on load
    checkAuth();


    // ─── Suggestion Chips ───────────────────────────────────────────────────
    document.querySelectorAll('.chip[data-question]').forEach(function (chip) {
        chip.addEventListener('click', function () {
            questionInput.value = chip.getAttribute('data-question');
            submitQuestion();
        });
    });

    // ─── Form Submit ────────────────────────────────────────────────────────
    inputForm.addEventListener('submit', function (e) {
        e.preventDefault();
        submitQuestion();
    });

    async function submitQuestion() {
        var question = questionInput.value.trim();
        if (!question || isProcessing) return;

        isProcessing = true;
        sendBtn.disabled = true;
        questionInput.value = '';

        if (welcomeSection) {
            welcomeSection.style.display = 'none';
        }

        addMessage(question, 'user');
        var loadingId = showLoading();

        try {
            var res = await fetch('/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: question }),
            });

            if (res.status === 401) {
                removeLoading(loadingId);
                showPage('page-login');
                showToast('Session expired. Please login again.', 'error');
                return;
            }

            var data = await res.json();
            removeLoading(loadingId);

            if (data.error) {
                addMessage(data.error, 'ai', { grade: 'error' });
            } else {
                addMessage(data.answer, 'ai', {
                    grade: data.grade,
                    retryCount: data.retry_count,
                    docsFound: data.documents_found,
                    timeTaken: data.time_taken,
                    rewrittenQuestion: data.rewritten_question,
                });
            }
        } catch (err) {
            removeLoading(loadingId);
            addMessage('Connection error. Make sure the server is running.', 'ai', {
                grade: 'error',
            });
        } finally {
            isProcessing = false;
            sendBtn.disabled = false;
            questionInput.focus();
        }
    }

    // ─── Add Message ────────────────────────────────────────────────────────
    function addMessage(text, type, meta) {
        meta = meta || {};
        var messageDiv = document.createElement('div');
        messageDiv.className = 'message message-' + type;

        if (type === 'user') {
            messageDiv.innerHTML = '<div class="message-bubble">' + escapeHtml(text) + '</div>';
        } else {
            var pipelineTags = buildPipelineTags(meta);
            messageDiv.innerHTML =
                '<div class="ai-header">' +
                    '<div class="ai-avatar au-logo-small">AU</div>' +
                    '<span class="ai-name">AU Chatbot</span>' +
                '</div>' +
                '<div class="message-bubble">' + formatAnswer(text) + '</div>' +
                pipelineTags;
        }

        messagesContainer.appendChild(messageDiv);
        scrollToBottom();
    }

    // ─── Pipeline Tags ──────────────────────────────────────────────────────
    function buildPipelineTags(meta) {
        if (!meta || meta.grade === 'error') return '';
        var tags = [];

        if (meta.grade === 'pass') {
            tags.push('<span class="pipeline-tag tag-pass">&#9989; Grounded in AU Docs</span>');
        } else if (meta.grade === 'fail') {
            tags.push('<span class="pipeline-tag tag-fail">&#10060; Not Grounded</span>');
        }
        if (meta.docsFound !== undefined) {
            tags.push('<span class="pipeline-tag tag-info">&#128196; ' + meta.docsFound + ' docs retrieved</span>');
        }
        if (meta.retryCount > 0) {
            tags.push('<span class="pipeline-tag tag-retry">&#128260; ' + meta.retryCount + (meta.retryCount === 1 ? ' retry' : ' retries') + '</span>');
        }
        if (meta.rewrittenQuestion) {
            tags.push('<span class="pipeline-tag tag-retry" title="' + escapeHtml(meta.rewrittenQuestion) + '">&#9999;&#65039; Question rewritten</span>');
        }
        if (meta.timeTaken) {
            tags.push('<span class="pipeline-tag tag-info">&#9889; ' + meta.timeTaken + 's</span>');
        }
        return tags.length > 0 ? '<div class="pipeline-info">' + tags.join('') + '</div>' : '';
    }

    // ─── Loading Dots ───────────────────────────────────────────────────────
    function showLoading() {
        var id = 'loading-' + (++loadingCounter);
        var div = document.createElement('div');
        div.className = 'message message-ai';
        div.id = id;
        div.innerHTML =
            '<div class="ai-header">' +
                '<div class="ai-avatar au-logo-small">AU</div>' +
                '<span class="ai-name">AU Chatbot</span>' +
            '</div>' +
            '<div class="message-bubble">' +
                '<div class="loading-dots"><span></span><span></span><span></span></div>' +
            '</div>';
        messagesContainer.appendChild(div);
        scrollToBottom();
        return id;
    }

    function removeLoading(id) {
        var el = document.getElementById(id);
        if (el) el.remove();
    }

    // ─── Helpers ────────────────────────────────────────────────────────────
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatAnswer(text) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function scrollToBottom() {
        requestAnimationFrame(function () {
            chatArea.scrollTop = chatArea.scrollHeight;
        });
    }

    // ═══════════════════════════════════════════════════════════════════════
    // ─── Knowledge Base Manager (Admin Only) ────────────────────────────
    // ═══════════════════════════════════════════════════════════════════════

    function openDrawer() {
        kbDrawer.classList.add('active');
        kbOverlay.classList.add('active');
        fab.classList.add('active');
        fetchDocuments();
    }

    function closeDrawer() {
        kbDrawer.classList.remove('active');
        kbOverlay.classList.remove('active');
        fab.classList.remove('active');
    }

    function toggleDrawer() {
        if (kbDrawer.classList.contains('active')) {
            closeDrawer();
        } else {
            openDrawer();
        }
    }

    fab.addEventListener('click', toggleDrawer);
    kbOverlay.addEventListener('click', closeDrawer);
    kbCloseBtn.addEventListener('click', closeDrawer);

    // ─── Fetch Documents ────────────────────────────────────────────────
    async function fetchDocuments() {
        kbDocList.innerHTML = '<div class="kb-loading">Loading documents...</div>';

        try {
            var res = await fetch('/api/documents');
            if (res.status === 401 || res.status === 403) {
                kbDocList.innerHTML = '<div class="kb-error">Unauthorized. Admin access required.</div>';
                return;
            }
            
            var data = await res.json();
            var docs = data.documents || [];

            if (docs.length === 0) {
                kbDocList.innerHTML =
                    '<div class="kb-empty">' +
                        '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' +
                            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                            '<polyline points="14 2 14 8 20 8"/>' +
                        '</svg>' +
                        'No documents yet. Upload a file or add text above!' +
                    '</div>';
                return;
            }

            kbDocList.innerHTML = '';
            docs.forEach(function (doc) {
                var sizeKb = (doc.size_bytes / 1024).toFixed(1);
                var item = document.createElement('div');
                item.className = 'kb-doc-item';
                item.innerHTML =
                    '<div class="kb-doc-info">' +
                        '<div class="kb-doc-name">' + escapeHtml(doc.filename) + '</div>' +
                        '<div class="kb-doc-meta">' +
                            '<span>' + sizeKb + ' KB</span>' +
                            '<span>' + doc.chunk_count + ' chunks</span>' +
                        '</div>' +
                    '</div>';

                var delBtn = document.createElement('button');
                delBtn.className = 'kb-doc-delete';
                delBtn.title = 'Delete this document';
                delBtn.innerHTML =
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                        '<polyline points="3 6 5 6 21 6"/>' +
                        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>' +
                    '</svg>';
                delBtn.addEventListener('click', function () {
                    deleteDocument(doc.filename);
                });

                item.appendChild(delBtn);
                kbDocList.appendChild(item);
            });
        } catch (err) {
            kbDocList.innerHTML = '<div class="kb-loading">Failed to load documents.</div>';
        }
    }

    // ─── File Upload (Dropzone) ─────────────────────────────────────────
    dropzone.addEventListener('click', function () {
        fileInput.click();
    });

    dropzone.addEventListener('dragover', function (e) {
        e.preventDefault();
        dropzone.classList.add('drag-over');
    });

    dropzone.addEventListener('dragleave', function () {
        dropzone.classList.remove('drag-over');
    });

    dropzone.addEventListener('drop', function (e) {
        e.preventDefault();
        dropzone.classList.remove('drag-over');
        var file = e.dataTransfer.files[0];
        if (file) uploadFile(file);
    });

    fileInput.addEventListener('change', function () {
        var file = fileInput.files[0];
        if (file) uploadFile(file);
        fileInput.value = '';
    });

    let pendingImageFile = null;
    const imageDescModal = document.getElementById('image-desc-modal');
    const imageDescInput = document.getElementById('image-desc-input');
    const confirmImageBtn = document.getElementById('confirm-image-btn');
    const cancelImageBtn = document.getElementById('cancel-image-btn');

    cancelImageBtn.addEventListener('click', () => {
        imageDescModal.style.display = 'none';
        pendingImageFile = null;
        imageDescInput.value = '';
    });

    confirmImageBtn.addEventListener('click', () => {
        const desc = imageDescInput.value.trim();
        if (!desc) {
            showToast('Please enter a description for the image', 'error');
            return;
        }
        imageDescModal.style.display = 'none';
        executeUpload(pendingImageFile, desc);
        pendingImageFile = null;
        imageDescInput.value = '';
    });

    function uploadFile(file) {
        const isImage = file.name.match(/\.(jpg|jpeg|png)$/i);
        const isTxt = file.name.endsWith('.txt');

        if (!isTxt && !isImage) {
            showToast('Only .txt, .jpg, and .png files are supported.', 'error');
            return;
        }

        if (isImage) {
            pendingImageFile = file;
            imageDescModal.style.display = 'block';
            imageDescInput.focus();
        } else {
            executeUpload(file, null);
        }
    }

    async function executeUpload(file, description) {
        var formData = new FormData();
        formData.append('file', file);
        if (description) {
            formData.append('description', description);
        }
        
        showToast('Uploading "' + file.name + '"...', 'success');

        try {
            var res = await fetch('/api/documents/upload', {
                method: 'POST',
                body: formData,
            });
            var data = await res.json();

            if (res.ok) {
                showToast(data.message || 'File added!', 'success');
                fetchDocuments();
            } else {
                showToast(data.error || 'Upload failed.', 'error');
            }
        } catch (err) {
            showToast('Upload failed. Check server connection.', 'error');
        }
    }

    // ─── Add Text Document ──────────────────────────────────────────────
    addTextBtn.addEventListener('click', async function () {
        var titleInput = document.getElementById('text-title');
        var contentInput = document.getElementById('text-content');

        var title = titleInput.value.trim();
        var content = contentInput.value.trim();

        if (!title) {
            showToast('Please enter a document title.', 'error');
            titleInput.focus();
            return;
        }
        if (!content) {
            showToast('Please enter some content.', 'error');
            contentInput.focus();
            return;
        }

        addTextBtn.disabled = true;

        try {
            var res = await fetch('/api/documents/text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: title, content: content }),
            });
            var data = await res.json();

            if (res.ok) {
                showToast('"' + data.filename + '" created with ' + data.chunks_added + ' chunks!', 'success');
                titleInput.value = '';
                contentInput.value = '';
                fetchDocuments();
            } else {
                showToast(data.error || 'Failed to add document.', 'error');
            }
        } catch (err) {
            showToast('Failed to add. Check server connection.', 'error');
        } finally {
            addTextBtn.disabled = false;
        }
    });

    // ─── Delete Document ────────────────────────────────────────────────
    async function deleteDocument(filename) {
        if (!confirm('Delete "' + filename + '" from the knowledge base?\n\nThis will remove the file and all its chunks from the database.')) {
            return;
        }

        try {
            var res = await fetch('/api/documents/' + encodeURIComponent(filename), {
                method: 'DELETE',
            });
            var data = await res.json();

            if (res.ok) {
                showToast('Deleted "' + filename + '" (' + data.chunks_removed + ' chunks removed).', 'success');
                fetchDocuments();
            } else {
                showToast(data.error || 'Delete failed.', 'error');
            }
        } catch (err) {
            showToast('Delete failed. Check server connection.', 'error');
        }
    }

    // ─── Toast Notifications ────────────────────────────────────────────
    function showToast(message, type) {
        type = type || 'success';
        var container = document.getElementById('toast-container');
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        var icon = type === 'success' ? '&#9989;' : '&#9888;&#65039;';
        toast.innerHTML = '<span class="toast-icon">' + icon + '</span><span>' + escapeHtml(message) + '</span>';
        container.appendChild(toast);

        setTimeout(function () {
            toast.style.animation = 'toastOut 0.3s ease-out forwards';
            setTimeout(function () { toast.remove(); }, 300);
        }, 3500);
    }

}); // end DOMContentLoaded

// ─── Password Visibility Toggle (global) ────────────────────────────────────
function togglePassword(inputId, btn) {
    var input = document.getElementById(inputId);
    var eyeOpen = btn.querySelector('.eye-open');
    var eyeClosed = btn.querySelector('.eye-closed');

    if (input.type === 'password') {
        input.type = 'text';
        eyeOpen.style.display = 'none';
        eyeClosed.style.display = 'block';
    } else {
        input.type = 'password';
        eyeOpen.style.display = 'block';
        eyeClosed.style.display = 'none';
    }
}
