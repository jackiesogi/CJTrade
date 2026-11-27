/**
 * LOGIN CONTROLLER
 * Handles session authentication and JWT storage.
 */

document.getElementById('login-form').onsubmit = async (e) => {
    e.preventDefault();

    const errorDiv = document.getElementById('error-msg');
    errorDiv.classList.add('hidden');

    // OAuth2PasswordRequestForm expects FormData (URL encoded)
    const formData = new FormData();
    formData.append('username', document.getElementById('username').value);
    formData.append('password', document.getElementById('password').value);

    try {
        const resp = await fetch('/api/v1/auth/login', {
            method: 'POST',
            body: formData
        });

        const data = await resp.json();

        if (resp.ok) {
            // Store token for global authenticated requests
            localStorage.setItem('finhub_token', data.access_token);
            // Redirect to main ledger dashboard
            window.location.href = '/';
        } else {
            // Display authentication failure (e.g., Invalid credentials)
            errorDiv.innerText = data.detail || "Authentication failed. Please check your credentials.";
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.innerText = "System unreachable. Check your connection.";
        errorDiv.classList.remove('hidden');
        console.error("Critical Login Error:", err);
    }
};

/**
 * PROACTIVE CLEANUP
 * Clear any stale sessions when visiting the login page.
 */
window.onload = () => {
    localStorage.removeItem('finhub_token');
};
