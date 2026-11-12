(() => {
  const rangeInputs = document.querySelectorAll('input[type="range"]');
  rangeInputs.forEach((input) => {
    input.addEventListener("input", () => {
      input.setAttribute("aria-valuenow", input.value);
    });
  });
})();
