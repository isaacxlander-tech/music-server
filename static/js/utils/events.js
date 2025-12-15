// Simple event handler that works on all devices
export function addEventListeners(element, callback) {
    if (!element) return;
    
    // Store touch data on element to avoid sharing between elements
    if (!element._touchData) {
        element._touchData = {
            startTime: 0,
            startX: 0,
            startY: 0,
            moved: false,
            lastTouchTime: 0
        };
    }
    
    const touchData = element._touchData;
    
    // Touch events for mobile
    element.addEventListener('touchstart', (e) => {
        touchData.startTime = Date.now();
        touchData.startX = e.touches[0].clientX;
        touchData.startY = e.touches[0].clientY;
        touchData.moved = false;
        element.style.opacity = '0.7';
    }, { passive: true });
    
    element.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) {
            const xDiff = Math.abs(e.touches[0].clientX - touchData.startX);
            const yDiff = Math.abs(e.touches[0].clientY - touchData.startY);
            if (xDiff > 10 || yDiff > 10) {
                touchData.moved = true;
                element.style.opacity = '';
            }
        }
    }, { passive: true });
    
    element.addEventListener('touchend', (e) => {
        element.style.opacity = '';
        touchData.lastTouchTime = Date.now();
        
        const timeDiff = Date.now() - touchData.startTime;
        const touchEndX = e.changedTouches[0].clientX;
        const touchEndY = e.changedTouches[0].clientY;
        const xDiff = Math.abs(touchEndX - touchData.startX);
        const yDiff = Math.abs(touchEndY - touchData.startY);
        
        // Only trigger if it's a tap (not a swipe)
        if (!touchData.moved && timeDiff < 500 && xDiff < 20 && yDiff < 20) {
            e.preventDefault();
            e.stopPropagation();
            callback(e);
        }
        
        touchData.moved = false;
    }, { passive: false });
    
    // Click for desktop
    element.addEventListener('click', (e) => {
        // Only handle click if no recent touch
        const timeSinceTouch = Date.now() - touchData.lastTouchTime;
        if (timeSinceTouch > 300) {
            callback(e);
        }
    });
}
