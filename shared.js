// ===== Assistencialão - Shared JS =====

// Chart.js Global Config
Chart.defaults.color = '#a0a0b8';
Chart.defaults.borderColor = '#2a2a40';
Chart.defaults.font.family = "'Segoe UI', sans-serif";

const COLORS = {
    red: '#e63946',
    redLight: '#ff6b6b',
    green: '#2ec4b6',
    yellow: '#f4a261',
    blue: '#457b9d',
    blueLight: '#6bb5d9',
    purple: '#9b59b6',
};

// Scatter data generator
function generateScatterData(baseX, baseY, n, spreadX, spreadY, correlation) {
    const data = [];
    for (let i = 0; i < n; i++) {
        const x = baseX + (Math.random() - 0.5) * spreadX;
        const noise = (Math.random() - 0.5) * spreadY;
        const y = baseY + correlation * (x - baseX) * (spreadY / spreadX) + noise;
        data.push({ x: Math.max(2, Math.min(55, x)), y: Math.max(5, Math.min(60, y)) });
    }
    return data;
}

// Scroll animation (IntersectionObserver)
document.addEventListener('DOMContentLoaded', function() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.fade-in').forEach(el => observer.observe(el));

    // Mobile nav toggle
    const toggle = document.querySelector('.nav-toggle');
    const links = document.querySelector('.nav-links');
    if (toggle && links) {
        toggle.addEventListener('click', () => {
            links.classList.toggle('open');
        });
    }
});
