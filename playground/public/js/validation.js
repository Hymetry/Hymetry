document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('contactForm');
    const successMessage = document.getElementById('successMessage');

    // Validation functions
    const validators = {
        name: (value) => {
            if (!value.trim()) return 'Name is required';
            if (value.length < 2) return 'Name must be at least 2 characters long';
            return '';
        },
        email: (value) => {
            if (!value.trim()) return 'Email is required';
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) return 'Please enter a valid email address';
            return '';
        },
        message: (value) => {
            if (!value.trim()) return 'Message is required';
            if (value.length < 10) return 'Message must be at least 10 characters long';
            return '';
        }
    };

    // Show error message
    function showError(inputId, message) {
        const input = document.getElementById(inputId);
        const errorElement = document.getElementById(`${inputId}Error`);
        input.classList.add('is-invalid');
        errorElement.textContent = message;
    }

    // Clear error message
    function clearError(inputId) {
        const input = document.getElementById(inputId);
        const errorElement = document.getElementById(`${inputId}Error`);
        input.classList.remove('is-invalid');
        errorElement.textContent = '';
    }

    // Validate single field
    function validateField(field) {
        const value = field.value;
        const validator = validators[field.id];
        const error = validator(value);
        
        if (error) {
            showError(field.id, error);
            return false;
        }
        
        clearError(field.id);
        return true;
    }

    // Validate all fields
    function validateForm() {
        let isValid = true;
        ['name', 'email', 'message'].forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (!validateField(field)) {
                isValid = false;
            }
        });
        return isValid;
    }

    // Handle form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (!validateForm()) {
            return;
        }

        const formData = {
            name: document.getElementById('name').value,
            email: document.getElementById('email').value,
            message: document.getElementById('message').value
        };

        try {
            const response = await fetch('/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            const result = await response.json();

            if (result.success) {
                form.reset();
                successMessage.textContent = result.message;
                successMessage.style.display = 'block';
                setTimeout(() => {
                    successMessage.style.display = 'none';
                }, 3000);
            }
        } catch (error) {
            console.error('Error submitting form:', error);
            alert('An error occurred while submitting the form. Please try again.');
        }
    });

    // Real-time validation
    ['name', 'email', 'message'].forEach(fieldId => {
        const field = document.getElementById(fieldId);
        field.addEventListener('blur', () => validateField(field));
        field.addEventListener('input', () => {
            if (field.classList.contains('is-invalid')) {
                validateField(field);
            }
        });
    });
}); 