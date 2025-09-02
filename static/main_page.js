function initializeCarousel(currentWeek = 0) {
    const stage = document.getElementById('stage');
    const items = Array.from(stage.querySelectorAll('.item'));
    const prev = document.getElementById('prev');
    const next = document.getElementById('next');
    
    // 서버에서 전달받은 현재 주차를 초기 인덱스로 설정
    let index = Math.max(0, Math.min(20, currentWeek));

    const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
    const getVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim().replace('px', '');

    function render() {
        const gapY = parseFloat(getVar('--gap-y'));
        const ZC = parseFloat(getVar('--z-center'));
        const ZN = parseFloat(getVar('--z-near'));
        const ZF = parseFloat(getVar('--z-far'));

        items.forEach((el, i) => {
            const off = i - index;
            const abs = Math.abs(off);
            const y = off * gapY;
            const depth = (off === 0) ? ZC : (abs === 1 ? ZN : ZF);
            const scale = (off === 0) ? 1 : (abs === 1 ? 0.96 : 0.9);
            
            el.style.transform = `translate(-50%,-50%) translate3d(0, ${y}px, ${depth}px) scale(${scale})`;
            el.style.opacity = 1;
            el.style.zIndex = String(100 - abs * 10);
            el.classList.toggle('is-center', off === 0);
        });

        updateButtons();
    }

    function go(dir) {
        const n = items.length;
        index = clamp(index + dir, 0, n - 1);
        render();
    }

    function updateButtons() {
        const n = items.length;
        prev.disabled = (index === 0);
        next.disabled = (index === n - 1);
    }

    // 이벤트 리스너 등록
    prev.addEventListener('click', () => go(-1));
    next.addEventListener('click', () => go(1));

    window.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowUp') go(-1);
        if (e.key === 'ArrowDown') go(1);
        if (e.key === 'ArrowLeft') go(-1);
        if (e.key === 'ArrowRight') go(1);
    });

    // 세로 스와이프 처리
    let startY = null;
    let tracking = false;
    
    const onStart = y => {
        startY = y;
        tracking = true;
    };
    
    const onMove = y => {
        if (!tracking || startY === null) return;
        const dy = y - startY;
        if (Math.abs(dy) > 48) {
            if (dy < 0) go(1);
            else go(-1);
            tracking = false;
            startY = null;
        }
    };
    
    const onEnd = () => {
        tracking = false;
        startY = null;
    };

    stage.addEventListener('pointerdown', e => onStart(e.clientY));
    stage.addEventListener('pointermove', e => onMove(e.clientY));
    stage.addEventListener('pointerup', onEnd);
    stage.addEventListener('pointerleave', onEnd);
    stage.addEventListener('pointercancel', onEnd);

    // 초기 렌더링
    render();
}

// DOM이 로드되면 초기화 함수 준비
document.addEventListener('DOMContentLoaded', () => {
    // HTML에서 전달받은 currentWeek 값으로 초기화
    if (typeof window.currentWeek !== 'undefined') {
        initializeCarousel(window.currentWeek);
    } else {
        initializeCarousel(0);
    }
});