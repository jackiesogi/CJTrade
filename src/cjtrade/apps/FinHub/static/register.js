/**
 * REGISTRATION CONTROLLER
 * Handles identity creation and API interaction.
 */

document.getElementById('register-form').onsubmit = async (e) => {
    e.preventDefault();

    const errorDiv = document.getElementById('error-msg');
    const submitBtn = document.getElementById('submit-btn');

    // Reset state
    errorDiv.classList.add('hidden');

    const payload = {
        username: document.getElementById('username').value,
        email: document.getElementById('email').value,
        password: document.getElementById('password').value
    };

    try {
        const resp = await fetch('/api/v1/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await resp.json();

        if (resp.ok) {
            // Visual feedback for successful identity creation
            submitBtn.innerText = 'ACCOUNT CREATED!';
            submitBtn.classList.replace('bg-slate-900', 'bg-emerald-500');

            setTimeout(() => {
                window.location.href = '/login';
            }, 1000);
        } else {
            // Display API-specific error details (e.g., User already exists)
            errorDiv.innerText = data.detail || "Registration rejected by server.";
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.innerText = "Connection lost. Please check your network.";
        errorDiv.classList.remove('hidden');
        console.error("Critical Registration Error:", err);
    }
};

// Clear session to avoid conflicts if someone tries to register while logged in
window.onload = () => {
    localStorage.removeItem('finhub_token');
};
