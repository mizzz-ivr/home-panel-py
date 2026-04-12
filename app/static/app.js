setTimeout(() => {
  const error = document.querySelector('.error');
  if (error) {
    error.style.transition = 'opacity 0.4s';
    error.style.opacity = '0';
  }
}, 4000);
