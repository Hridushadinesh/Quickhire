// Main JavaScript file for QuickHire

// Form validation for password confirmation
document.addEventListener('DOMContentLoaded', function() {
    const registerForm = document.querySelector('form[action="/register"]');
    if (registerForm) {
        // Password confirmation validation
        registerForm.addEventListener('submit', function(e) {
            const password = document.getElementById('password');
            const confirmPassword = document.getElementById('confirm_password');
            
            if (password.value !== confirmPassword.value) {
                e.preventDefault();
                alert('Passwords do not match!');
            }
        });

        // Handle user type selection
        const userTypeSelect = document.getElementById('user_type');
        const workerFields = document.querySelectorAll('.worker-field');

        function toggleWorkerFields() {
            const isWorker = userTypeSelect.value === 'worker';
            workerFields.forEach(field => {
                field.style.display = isWorker ? 'block' : 'none';
                // Make location required for workers
                const input = field.querySelector('input');
                if (input) {
                    input.required = isWorker;
                }
            });
        }

        // Initial toggle
        if (userTypeSelect) {
            toggleWorkerFields();
            userTypeSelect.addEventListener('change', toggleWorkerFields);
        }
    }
});

// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            alert.style.opacity = '0';
            setTimeout(function() {
                alert.remove();
            }, 500);
        }, 5000);
    });
}); 