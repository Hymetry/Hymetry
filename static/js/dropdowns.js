/**
 * Reusable script for handling dropdown menus.
 */
function toggleDropdown(dropdownMenu, forceHide = false) {
    const dropdownButton = document.querySelector(`[data-dropdown-toggle="#${dropdownMenu.id}"]`);
    const isHidden = dropdownMenu.classList.contains('hidden');

    if (forceHide || !isHidden) {
        dropdownMenu.classList.add('hidden');
        dropdownMenu.classList.remove("opacity-100", "scale-100");
        dropdownMenu.classList.add("opacity-0", "scale-95");
        if (dropdownButton) dropdownButton.setAttribute("aria-expanded", "false");
    } else {
        dropdownMenu.classList.remove('hidden');
        setTimeout(() => {
            dropdownMenu.classList.remove("opacity-0", "scale-95");
            dropdownMenu.classList.add("opacity-100", "scale-100");
        }, 10);
        if (dropdownButton) dropdownButton.setAttribute("aria-expanded", "true");
    }
}

document.addEventListener('click', e => {
    const clickedDropdownButton = e.target.closest('[data-dropdown-toggle]');
    const allDropdowns = document.querySelectorAll('[data-dropdown-menu]');

    if (clickedDropdownButton) {
        const targetDropdownId = clickedDropdownButton.getAttribute('data-dropdown-toggle');
        const targetDropdown = document.querySelector(targetDropdownId);
        allDropdowns.forEach(dropdown => {
            if (dropdown !== targetDropdown) {
                toggleDropdown(dropdown, true);
            }
        });
        toggleDropdown(targetDropdown);
    } else {
        allDropdowns.forEach(dropdown => {
            toggleDropdown(dropdown, true);
        });
    }
});

document.querySelectorAll('[data-dropdown-menu]').forEach(dropdown => {
    dropdown.classList.add("hidden", "transform", "opacity-0", "scale-95");
});