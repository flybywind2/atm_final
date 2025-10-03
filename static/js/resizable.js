// resizable.js - BP 사례 패널 너비 조절 스크립트

(function () {
    const panel = document.getElementById('bp-cases-floating');
    if (!panel) return;

    const handle = document.createElement('div');
    handle.className = 'bp-resize-handle';
    panel.insertBefore(handle, panel.firstChild);

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    const MIN_WIDTH = 260;
    const MAX_WIDTH = 600;

    const onMouseMove = (event) => {
        if (!isResizing) return;
        const delta = startX - event.clientX;
        let newWidth = startWidth + delta;
        newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, newWidth));
        panel.style.width = `${newWidth}px`;
    };

    const stopResize = () => {
        if (!isResizing) return;
        isResizing = false;
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', stopResize);
    };

    handle.addEventListener('mousedown', (event) => {
        event.preventDefault();
        isResizing = true;
        startX = event.clientX;
        startWidth = panel.getBoundingClientRect().width;
        document.body.classList.add('resizing');
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', stopResize);
    });
})();
