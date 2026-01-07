// Main JavaScript for Twitter Bookmarks

// UpdateBatcher class for batching rapid updates (250ms window)
class UpdateBatcher {
    constructor(batchWindow = 250) {
        this.batchWindow = batchWindow;
        this.pendingUpdates = new Map();
        this.batchTimer = null;
    }
    
    queueUpdate(elementId, updateFn) {
        this.pendingUpdates.set(elementId, updateFn);
        
        if (!this.batchTimer) {
            this.batchTimer = setTimeout(() => {
                this.applyBatch();
            }, this.batchWindow);
        }
    }
    
    applyBatch() {
        this.pendingUpdates.forEach((updateFn, elementId) => {
            try {
                updateFn();
            } catch (error) {
                console.error(`Error applying update for ${elementId}:`, error);
            }
        });
        this.pendingUpdates.clear();
        this.batchTimer = null;
    }
    
    flush() {
        if (this.batchTimer) {
            clearTimeout(this.batchTimer);
            this.batchTimer = null;
        }
        this.applyBatch();
    }
}

// Global update batcher instance
const updateBatcher = new UpdateBatcher(250);

// Apply update with visual feedback
function applyUpdateWithFeedback(element, newContent) {
    if (!element) return;
    
    element.innerHTML = newContent;
    element.classList.add('update-highlight');
    setTimeout(() => {
        element.classList.remove('update-highlight');
    }, 500);
}

// Connection status management
let connectionStatusIndicator = null;
let connectionState = 'disconnected';

function updateConnectionStatus(state) {
    connectionState = state;
    if (connectionStatusIndicator) {
        connectionStatusIndicator.className = `connection-status ${state}`;
        const statusText = {
            'connected': '● Connected',
            'disconnected': '● Disconnected',
            'reconnecting': '● Reconnecting...'
        };
        connectionStatusIndicator.textContent = statusText[state] || '● Unknown';
    }
}

// SSE reconnection logic with exponential backoff
let reconnectAttempts = 0;
const maxReconnectAttempts = 10;
const baseReconnectDelay = 1000; // 1 second

function reconnectSSE() {
    if (reconnectAttempts >= maxReconnectAttempts) {
        updateConnectionStatus('disconnected');
        console.error('Max reconnection attempts reached');
        return;
    }
    
    updateConnectionStatus('reconnecting');
    const delay = Math.min(baseReconnectDelay * Math.pow(2, reconnectAttempts), 30000); // Max 30 seconds
    reconnectAttempts++;
    
    setTimeout(() => {
        // htmx will automatically reconnect if the connection is lost
        // This is just for status indication
        updateConnectionStatus('connected');
        reconnectAttempts = 0;
    }, delay);
}

// Date validation utility
function isDateAvailable(selectedDate, availableDates) {
    if (!availableDates || availableDates.length === 0) return false;
    // availableDates are already ISO date strings (YYYY-MM-DD)
    const selectedDateStr = selectedDate instanceof Date ? selectedDate.toISOString().split('T')[0] : selectedDate;
    return availableDates.includes(selectedDateStr);
}

// Find nearest available date
function findNearestAvailableDate(selectedDate, availableDates) {
    if (!availableDates || availableDates.length === 0) return null;
    
    const selected = new Date(selectedDate);
    let nearest = null;
    let minDiff = Infinity;
    
    availableDates.forEach(dateStr => {
        const dateObj = new Date(dateStr);
        const diff = Math.abs(selected - dateObj);
        if (diff < minDiff) {
            minDiff = diff;
            nearest = dateStr; // Keep as string for return
        }
    });
    
    return nearest;
}

// Initialize date picker validation
function initializeDatePickerValidation() {
    const dateInputs = document.querySelectorAll('input[type="date"]');
    const availableDatesData = document.getElementById('available-dates-data');
    
    if (!availableDatesData || dateInputs.length === 0) return;
    
    let availableDates = [];
    try {
        availableDates = JSON.parse(availableDatesData.textContent || '[]');
    } catch (e) {
        console.error('Error parsing available dates:', e);
        return;
    }
    
    dateInputs.forEach(input => {
        input.addEventListener('change', function(e) {
            const selectedDate = e.target.value;
            if (selectedDate && !isDateAvailable(selectedDate, availableDates)) {
                // Find nearest available date
                const nearest = findNearestAvailableDate(selectedDate, availableDates);
                if (nearest) {
                    alert(`No content available for ${selectedDate}. Redirecting to nearest available date: ${nearest}`);
                    // Update the date picker and trigger navigation
                    e.target.value = nearest;
                    if (typeof changeDate === 'function') {
                        changeDate(nearest);
                    } else {
                        // Fallback: update URL
                        const url = new URL(window.location.href);
                        url.searchParams.set('date', nearest);
                        window.location.href = url.toString();
                    }
                } else {
                    alert(`No content available for ${selectedDate}. Please select a different date.`);
                    // Reset to current date
                    const url = new URL(window.location.href);
                    const currentDate = url.searchParams.get('date') || new Date().toISOString().split('T')[0];
                    e.target.value = currentDate;
                }
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // Initialize date picker validation
    initializeDatePickerValidation();
    
    // Auto-hide messages - errors stay longer (15s), others 5s
    const messages = document.querySelectorAll('.alert');
    messages.forEach(function(message) {
        // Check if it's an error message
        const isError = message.classList.contains('alert-error') || 
                       message.classList.contains('alert-danger') ||
                       message.textContent.toLowerCase().includes('error');
        
        const delay = isError ? 15000 : 5000; // 15 seconds for errors, 5 for others
        
        setTimeout(function() {
            message.style.transition = 'opacity 0.5s';
            message.style.opacity = '0';
            setTimeout(function() {
                message.remove();
            }, 500);
        }, delay);
    });
    
    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const requiredFields = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredFields.forEach(function(field) {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('error');
                } else {
                    field.classList.remove('error');
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                alert('Please fill in all required fields.');
            }
        });
    });
    
    // Initialize connection status indicator if on status page
    connectionStatusIndicator = document.getElementById('connection-status-indicator');
    if (connectionStatusIndicator) {
        updateConnectionStatus('connected');
    }
    
    // Listen for htmx SSE events
    if (typeof htmx !== 'undefined') {
        document.body.addEventListener('htmx:sseError', function(event) {
            updateConnectionStatus('disconnected');
            reconnectSSE();
        });
        
        document.body.addEventListener('htmx:sseOpen', function(event) {
            updateConnectionStatus('connected');
            reconnectAttempts = 0;
        });
        
        document.body.addEventListener('htmx:sseClose', function(event) {
            updateConnectionStatus('disconnected');
            reconnectSSE();
        });
    }
});

