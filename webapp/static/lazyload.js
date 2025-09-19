(function(){
  const lazyClass = 'lazy';
  const loadedClass = 'loaded';

  function _firstUrlFromSrcset(srcset) {
    if(!srcset) return '';
    const parts = srcset.split(',').map(s => s.trim()).filter(Boolean);
    if(parts.length === 0) return '';
    return parts[0].split(/\s+/)[0];
  }

  function loadImage(img) {
    if(!img) return;
    const src = img.dataset.src;
    const srcset = img.dataset.srcset || img.dataset.srcSet || img.getAttribute('data-srcset');
    if(src) img.src = src;
    if(srcset) {
      try {
        img.srcset = srcset;
      } catch(e) {
        const first = _firstUrlFromSrcset(srcset);
        if(first) img.srcset = first;
      }
    }
    function onLoad(){
      img.classList.add(loadedClass);
      img.classList.remove(lazyClass);
      img.removeEventListener('load', onLoad);
    }
    img.addEventListener('load', onLoad);
    if(img.complete && img.naturalWidth) {
      img.classList.add(loadedClass);
      img.classList.remove(lazyClass);
    }
  }

  function initObserver() {
    const lazyImages = [].slice.call(document.querySelectorAll('img.' + lazyClass));
    if (lazyImages.length === 0) return true;
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const img = entry.target;
            loadImage(img);
            obs.unobserve(img);
          }
        });
      }, {
        root: null,
        rootMargin: '0px 0px 300px 0px',
        threshold: 0.01
      });

      lazyImages.forEach(img => observer.observe(img));
      window.lazyloadObserve = function(){
        document.querySelectorAll('img.' + lazyClass).forEach(i => observer.observe(i));
      };
      return true;
    }

    // fallback
    let active = false;
    let imgs = lazyImages;
    const lazyLoad = function() {
      if (active === false) {
        active = true;
        setTimeout(function() {
          imgs = imgs.filter(img => {
            if ((img.getBoundingClientRect().top <= window.innerHeight + 300 && img.getBoundingClientRect().bottom >= -300) &&
                getComputedStyle(img).display !== "none") {
              loadImage(img);
              return false;
            }
            return true;
          });
          if (imgs.length === 0) {
            document.removeEventListener("scroll", lazyLoad);
            window.removeEventListener("resize", lazyLoad);
            window.removeEventListener("orientationchange", lazyLoad);
          }
          active = false;
        }, 200);
      }
    };
    document.addEventListener('scroll', lazyLoad);
    window.addEventListener('resize', lazyLoad);
    window.addEventListener('orientationchange', lazyLoad);
    lazyLoad();
    window.lazyloadObserve = function(){};
    return true;
  }

  document.addEventListener("DOMContentLoaded", function() {
    initObserver();
  });

  window.lazyloadObserve = window.lazyloadObserve || null;
})();
