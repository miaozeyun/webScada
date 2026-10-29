/* webScada 官网脚本：仅负责移动端导航开关与年份，页面内容不依赖 JS 渲染（SEO/GEO 友好） */
(function () {
  var header = document.querySelector('.site-header');
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');

  /* 页头默认全透明（首屏画面不被遮挡），页面一滚动再切换为深色玻璃底 */
  if (header) {
    var syncHeader = function () {
      header.classList.toggle('is-scrolled', window.pageYOffset > 8);
    };
    syncHeader();
    window.addEventListener('scroll', syncHeader, { passive: true });
  }

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (header) header.classList.toggle('nav-open', open);
    });
  }


  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
})();
