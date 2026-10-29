/* webScada 官网 · 置顶案例实况轮播
 * 素材为分享页录制的真实运行画面（VP9 webm）；视频未就绪/不支持/减少动态偏好时，
 * 退化为同一画面的 Ken Burns 缓慢推近海报，保证首屏始终“在动”。
 * 无 JS 时首屏默认展示第 1 个案例海报，不影响内容与 SEO。
 */
(function () {
  var section = document.getElementById('showcase');
  if (!section) return;

  /* 视频区与切换条是同级两个 section：案例卡/箭头不在 #showcase 内，按全文档取 */
  var slides = Array.prototype.slice.call(document.querySelectorAll('.sc-slide'));
  var cases = Array.prototype.slice.call(document.querySelectorAll('.sc-case'));
  if (!slides.length || slides.length !== cases.length) return;

  var DURATION = 10000;
  var reduce =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var current = 0;
  var timer = null;
  var inView = true;
  var paused = false;

  /* ===== 首屏主色：光晕与页头色调跟随当前案例画面 ===== */
  var DEFAULT_ACCENT = [62, 224, 255];
  var accents = [];

  function rgb2hsl(R, G, B) {
    R /= 255; G /= 255; B /= 255;
    var mx = Math.max(R, G, B), mn = Math.min(R, G, B);
    var l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d) {
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      if (mx === R) h = ((G - B) / d + (G < B ? 6 : 0)) * 60;
      else if (mx === G) h = ((B - R) / d + 2) * 60;
      else h = ((R - G) / d + 4) * 60;
    }
    return [h, s, l];
  }

  function hsl2rgb(h, s, l) {
    function k(n) { return (n + h / 30) % 12; }
    var a = s * Math.min(l, 1 - l);
    function f(n) { return l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))); }
    return [f(0), f(8), f(4)].map(function (v) { return Math.round(v * 255); });
  }

  /** 抽海报主色：跳过暗背景与灰白读数，按「艳度² × 亮度」加权平均，
   *  再统一调到适合做光晕的饱和/明度，保证深色画面也能看出色相 */
  function sampleAccent(img) {
    try {
      var c = document.createElement('canvas');
      c.width = 48;
      c.height = 27;
      var g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0, 48, 27);
      var d = g.getImageData(0, 0, 48, 27).data;
      var r = 0, gr = 0, b = 0, wsum = 0;
      for (var i = 0; i < d.length; i += 4) {
        var R = d[i], G = d[i + 1], B = d[i + 2];
        var mx = Math.max(R, G, B), mn = Math.min(R, G, B);
        if (mx < 70) continue; /* 暗底 */
        var sat = (mx - mn) / mx;
        if (sat < 0.35) continue; /* 灰白文字与网格线 */
        var w = sat * sat * (mx / 255);
        r += R * w; gr += G * w; b += B * w; wsum += w;
      }
      if (!wsum) return null;
      var hsl = rgb2hsl(r / wsum, gr / wsum, b / wsum);
      return hsl2rgb(hsl[0], Math.max(hsl[1], 0.7), 0.62);
    } catch (e) {
      return null; /* file:// 等画布被污染：退回 data-accent */
    }
  }

  /** 取不到主色时的兜底：data-accent 由录制素材时定色 */
  function fallbackAccent(i) {
    var raw = slides[i].getAttribute('data-accent');
    if (!raw) return DEFAULT_ACCENT;
    var p = raw.split(',').map(Number);
    return p.length === 3 && p.every(function (v) { return isFinite(v); }) ? p : DEFAULT_ACCENT;
  }

  function accentOf(i) {
    if (accents[i]) return accents[i];
    var img = slides[i].querySelector('.sc-poster');
    if (img && img.complete && img.naturalWidth) {
      var got = sampleAccent(img);
      if (got) {
        accents[i] = got;
        return got;
      }
    }
    /* 海报未加载/取色失败：先用兜底色，且不写缓存，下次切换再试 */
    return fallbackAccent(i);
  }

  function applyAccent(i) {
    var a = accentOf(i);
    document.documentElement.style.setProperty('--sc-accent', a[0] + ',' + a[1] + ',' + a[2]);
    /* 同色相的浅色版：切换条序号/标签/箭头等小字用它，避免紫/琥珀在深底上对比度不足 */
    var hsl = rgb2hsl(a[0], a[1], a[2]);
    var soft = hsl2rgb(hsl[0], Math.min(Math.max(hsl[1], 0.5), 0.8), 0.78);
    document.documentElement.style.setProperty('--sc-accent-soft', soft.join(','));
    /* 光晕形态按案例切换：sea（地平线）/ dc（对角冷光）/ line（底部炉火） */
    section.setAttribute('data-glow', slides[i].getAttribute('data-glow') || 'sea');
  }

  function videoOf(i) {
    return slides[i].querySelector('video');
  }

  /** 挂 src 开始缓冲（每段只挂一次） */
  function ensureLoaded(i) {
    var v = videoOf(i);
    if (!v || v.src || !v.getAttribute('data-src')) return v;
    v.preload = 'auto';
    v.src = v.getAttribute('data-src');
    v.addEventListener('error', function () {
      slides[i].classList.remove('is-playing');
    });
    return v;
  }

  /** 判帧：Chrome 在首帧解码完成前可能把 video 绘成白底，抽一帧缩略图算平均亮度。
   *  返回 'ok' 可显示 / 'blank' 白底继续等 / 'unknown' 读不到像素（file:// 或跨源污染画布）。 */
  var probe = null;
  function frameState(v) {
    try {
      if (!probe) {
        probe = document.createElement('canvas');
        probe.width = 32;
        probe.height = 18;
      }
      var g = probe.getContext('2d', { willReadFrequently: true });
      g.drawImage(v, 0, 0, probe.width, probe.height);
      var d = g.getImageData(0, 0, probe.width, probe.height).data;
      var sum = 0;
      for (var i = 0; i < d.length; i += 4) sum += (d[i] + d[i + 1] + d[i + 2]) / 3;
      return sum / (d.length / 4) > 232 ? 'blank' : 'ok';
    } catch (e) {
      /* 画不出帧 = 尚未解码；读不到像素 = 画布被污染，二者都判不了白 */
      return 'unknown';
    }
  }

  /** 真正画出内容后才淡入视频：播放推进 + 已缓冲 + 抽帧不是白底，三者都满足才显示；
   *  海报始终垫在下方，所以等待期间画面是真实内容而不是白屏。 */
  function revealOnFirstFrame(i, v) {
    var slide = slides[i];
    var revealed = false;
    var startAt = Date.now();
    var unknown = 0;
    function reveal() {
      if (revealed) return;
      revealed = true;
      if (slide.classList.contains('is-active')) slide.classList.add('is-playing');
    }
    function tick() {
      if (revealed) return;
      var buffered = v.buffered.length > 0 && v.buffered.end(v.buffered.length - 1) > 0.4;
      var advanced = v.currentTime > 0.12;
      if (buffered && advanced) {
        var st = frameState(v);
        if (st === 'ok') {
          reveal();
          return;
        }
        if (st === 'unknown' && ++unknown >= 3) {
          /* 画布被判不了白（file://、跨源等）：别再等，直接显示，否则永远停在海报 */
          reveal();
          return;
        }
      }
      /* 已在正常播放且至少有一帧可画：等满 2.2s 就显示。
         个别显卡/解码路径抽帧恒为白，若只认探测结果会一直停在海报上，
         看上去就是“画面里的数据不动” */
      if (!v.paused && v.readyState >= 2 && v.currentTime > 0.3 && Date.now() - startAt > 2200) {
        reveal();
        return;
      }
      /* 长时间仍未确认可画：宁可停在真实海报，也不把白屏推给用户 */
      if (Date.now() - startAt > 12000) return;
      if (typeof v.requestVideoFrameCallback === 'function') v.requestVideoFrameCallback(tick);
      else window.setTimeout(tick, 100);
    }
    tick();
    /* 兜底：被自动播放策略拦下时 video 显示的是 poster（真实画面），可安全显示 */
    window.setTimeout(function () {
      if (v.paused) reveal();
    }, 1500);
  }

  /** 首屏播起来后把其余案例也缓冲好：切页即出画面，不再等加载 */
  var warmed = false;
  function warmOthers() {
    if (warmed) return;
    warmed = true;
    var mobile = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
    slides.forEach(function (_, k) {
      if (k === current) return;
      if (mobile && k !== (current + 1) % slides.length) return; /* 窄屏只预载下一段，省流量 */
      ensureLoaded(k);
    });
  }

  function play(i) {
    if (paused || !inView) return;
    var v = ensureLoaded(i);
    if (!v) return;
    revealOnFirstFrame(i, v);
    var p = v.play();
    if (p && p.catch) p.catch(function () {});
    /* 当前段一开始播就把其余案例缓冲下来（用户要求切页时第二段已就绪） */
    window.setTimeout(warmOthers, 300);
  }

  function pause(i) {
    var v = videoOf(i);
    if (v && !v.paused) v.pause();
  }

  function restartBar(i, animate) {
    var bar = cases[i].querySelector('.sc-bar i');
    if (!bar) return;
    bar.style.animation = 'none';
    if (!animate) {
      bar.style.width = '0';
      return;
    }
    void bar.offsetWidth; /* 强制回流，动画可重播 */
    bar.style.width = '';
    bar.style.animation = 'sc-progress ' + DURATION + 'ms linear forwards';
  }

  function startTimer() {
    stopTimer();
    if (reduce || !inView || paused) return;
    timer = window.setTimeout(function () {
      show((current + 1) % slides.length);
    }, DURATION);
  }

  function stopTimer() {
    if (timer) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  function show(i) {
    current = i;
    /* 光晕与页头色调跟随当前画面主色 */
    applyAccent(i);
    slides.forEach(function (s, k) {
      s.classList.toggle('is-active', k === i);
      if (k !== i) {
        pause(k);
        s.classList.remove('is-playing');
      }
    });
    cases.forEach(function (c, k) {
      var on = k === i;
      c.classList.toggle('is-active', on);
      c.setAttribute('aria-selected', on ? 'true' : 'false');
      restartBar(k, on && !reduce);
    });
    play(i);
    startTimer();
    /* 窄屏案例条是横向滚动：把当前卡滚进视野，否则高亮卡片在屏幕外，看起来“没跟着变” */
    var track = cases[i].parentNode;
    if (track && track.scrollWidth > track.clientWidth + 1) {
      var cr = cases[i].getBoundingClientRect();
      var tr = track.getBoundingClientRect();
      if (cr.left < tr.left || cr.right > tr.right) {
        var left = track.scrollLeft + (cr.left - tr.left) - (tr.width - cr.width) / 2;
        if (track.scrollTo) track.scrollTo({ left: left, behavior: 'smooth' });
        else track.scrollLeft = left;
      }
    }
    /* 任何一次切换后都补齐其余段，点哪张卡都不会白屏 */
    window.setTimeout(warmOthers, 800);
  }

  cases.forEach(function (c, k) {
    c.addEventListener('click', function () {
      show(k);
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll('.sc-arrow'), function (btn) {
    btn.addEventListener('click', function () {
      var dir = Number(btn.getAttribute('data-dir')) || 1;
      show((current + dir + slides.length) % slides.length);
    });
  });

  /* 触摸滑动（窄屏也能翻） */
  var touchX = null;
  section.addEventListener(
    'touchstart',
    function (e) {
      touchX = e.touches[0].clientX;
    },
    { passive: true }
  );
  section.addEventListener(
    'touchend',
    function (e) {
      if (touchX === null) return;
      var dx = e.changedTouches[0].clientX - touchX;
      touchX = null;
      if (Math.abs(dx) < 48) return;
      show((current + (dx < 0 ? 1 : -1) + slides.length) % slides.length);
    },
    { passive: true }
  );

  /* 首屏离开视口 / 切后台：停播省电，回来接着放 */
  function setActiveState(on) {
    inView = on;
    if (on) {
      show(current);
    } else {
      stopTimer();
      pause(current);
    }
  }

  if (!reduce && 'IntersectionObserver' in window) {
    new IntersectionObserver(
      function (entries) {
        setActiveState(entries[0].isIntersecting);
      },
      { threshold: 0.15 }
    ).observe(section);
  }

  document.addEventListener('visibilitychange', function () {
    setActiveState(!document.hidden && inView);
  });

  /* 首帧即开始轮播 */
  show(0);
})();
