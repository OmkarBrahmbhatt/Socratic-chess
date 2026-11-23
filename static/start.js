// Start page: after the participant picks a rating system, show either the
// rating-range question or, for "I don't have a rating", the experience question.
// Without JavaScript both questions stay visible and the server checks them.
(() => {
  const system = document.querySelector("#rating_system");
  const rated = document.querySelector("#rated-fields");
  const unrated = document.querySelector("#unrated-fields");
  if (!system || !rated || !unrated) return;
  const band = rated.querySelector("select");
  const experience = unrated.querySelector("select");
  const bandLabel = document.querySelector("#rating-band-label");

  const show = (section, select, visible) => {
    section.hidden = !visible;
    select.disabled = !visible;
    select.required = visible;
  };

  const update = () => {
    const value = system.value;
    show(rated, band, Boolean(value) && value !== "none");
    show(unrated, experience, value === "none");
    const option = system.selectedOptions[0];
    if (bandLabel && option && option.dataset.short) {
      bandLabel.textContent = `What is your ${option.dataset.short} rating?`;
    }
  };

  system.addEventListener("change", update);
  update();
})();
