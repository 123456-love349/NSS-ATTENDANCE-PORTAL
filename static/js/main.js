// ---------------------------------------------------------------------
// Persistent Theme Toggle (Saves preferences to localStorage)
// ---------------------------------------------------------------------
(function () {
    // Immediately apply saved theme before rendering to avoid flicker
    const savedTheme = localStorage.getItem('nss_theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', savedTheme);

    document.addEventListener('DOMContentLoaded', function () {
        const toggleBtn = document.getElementById('themeToggle');
        if (!toggleBtn) return;
        
        // Set initial icon state
        const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
        toggleBtn.innerHTML = isDark
            ? '<i class="bi bi-sun-fill"></i>'
            : '<i class="bi bi-moon-stars-fill"></i>';

        toggleBtn.addEventListener('click', function () {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            html.setAttribute('data-bs-theme', newTheme);
            localStorage.setItem('nss_theme', newTheme);
            
            toggleBtn.innerHTML = newTheme === 'dark'
                ? '<i class="bi bi-sun-fill"></i>'
                : '<i class="bi bi-moon-stars-fill"></i>';
        });
    });
})();

// ---------------------------------------------------------------------
// Bootstrap toast auto-init for flash messages
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.toast').forEach(function (el) {
        new bootstrap.Toast(el, { delay: 6000 }).show();
    });
});

// ---------------------------------------------------------------------
// Geolocation capture, used by the attendance form.
// Exposes window.NSS.captureLocation(onSuccess, onError)
// ---------------------------------------------------------------------
window.NSS = window.NSS || {};
window.NSS.captureLocation = function (onSuccess, onError) {
    if (!('geolocation' in navigator)) {
        onError('Geolocation is not supported by this browser.');
        return;
    }
    navigator.geolocation.getCurrentPosition(
        function (position) {
            onSuccess({
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                accuracy: position.coords.accuracy,
                timestamp: new Date(position.timestamp).toISOString(),
            });
        },
        function (error) {
            let message = 'Unable to retrieve your location.';
            if (error.code === error.PERMISSION_DENIED) {
                message = 'Location permission was denied. Attendance requires location access.';
            } else if (error.code === error.TIMEOUT) {
                message = 'Location request timed out. Please try again.';
            }
            onError(message);
        },
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
};

// ---------------------------------------------------------------------
// Attendance form submission (AJAX + JSON response)
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function () {
    const attendanceForm = document.getElementById('attendanceForm');
    if (!attendanceForm) return;

    const feedbackBox = document.getElementById('formFeedback');
    const submitBtn = document.getElementById('submitBtn');
    const originalBtnHtml = submitBtn ? submitBtn.innerHTML : '';

    attendanceForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        if (!attendanceForm.checkValidity()) {
            attendanceForm.reportValidity();
            return;
        }

        const formData = new FormData(attendanceForm);
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        }
        if (feedbackBox) {
            feedbackBox.className = 'alert alert-info mt-3';
            feedbackBox.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Saving your attendance...';
        }

        try {
            const response = await fetch(attendanceForm.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRF-Token': formData.get('csrf_token') || ''
                }
            });
            const payload = await response.json().catch(function () { return null; });

            if (response.ok && payload && payload.success) {
                if (feedbackBox) {
                    feedbackBox.className = 'alert alert-success mt-3';
                    feedbackBox.innerHTML = '<i class="bi bi-check-circle-fill"></i> ' + (payload.message || 'Attendance recorded successfully.');
                }
                if (payload.redirect_url) {
                    window.location.href = payload.redirect_url;
                }
                return;
            }

            const message = payload && payload.message ? payload.message : 'Attendance could not be saved. Please try again.';
            if (feedbackBox) {
                feedbackBox.className = 'alert alert-danger mt-3';
                feedbackBox.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i> ' + message;
            }
        } catch (error) {
            console.error('Attendance submission error:', error);
            if (feedbackBox) {
                feedbackBox.className = 'alert alert-danger mt-3';
                feedbackBox.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i> Attendance could not be saved. Please try again.';
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnHtml;
            }
        }
    });
});
