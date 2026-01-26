/**
 * Enhanced Dropdown Component
 * Converts all native select elements to custom styled dropdowns
 */
(function() {
    'use strict';

    // Initialize all dropdowns on page load
    document.addEventListener('DOMContentLoaded', function() {
        enhanceAllSelects();
    });

    // Also enhance dynamically added selects
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                if (node.nodeType === 1) { // Element node
                    if (node.tagName === 'SELECT' && !node.closest('.custom-select-wrapper')) {
                        enhanceSelect(node);
                    } else {
                        const selects = node.querySelectorAll && node.querySelectorAll('select:not(.custom-select-wrapper select)');
                        if (selects) {
                            selects.forEach(enhanceSelect);
                        }
                    }
                }
            });
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    function enhanceAllSelects() {
        // Select all single-select dropdowns, excluding multiple selects and already enhanced ones
        const selects = document.querySelectorAll('select:not([multiple]):not(.custom-select-wrapper select)');
        selects.forEach(function(select) {
            // Skip if it's inside a custom wrapper or is a multiple select
            if (!select.closest('.custom-select-wrapper') && !select.multiple) {
                enhanceSelect(select);
            }
        });
    }

    function enhanceSelect(select) {
        // Skip if already enhanced or if it's a multiple select
        if (select.closest('.custom-select-wrapper') || select.multiple) {
            return;
        }

        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'custom-select-wrapper';
        
        // Create custom select button
        const customSelect = document.createElement('div');
        customSelect.className = 'custom-select';
        
        const selectValue = document.createElement('span');
        selectValue.className = 'select-value';
        
        const selectArrow = document.createElement('span');
        selectArrow.className = 'select-arrow';
        selectArrow.innerHTML = '<i class="fas fa-chevron-down"></i>';
        
        customSelect.appendChild(selectValue);
        customSelect.appendChild(selectArrow);
        
        // Create dropdown
        const dropdown = document.createElement('div');
        dropdown.className = 'custom-select-dropdown';

        // Store references (needed when dropdown is "ported" to body while open)
        customSelect._customSelectWrapper = wrapper;
        customSelect._customSelectDropdown = dropdown;
        dropdown._customSelectButton = customSelect;
        
        // Function to populate dropdown options
        function populateDropdown() {
            dropdown.innerHTML = '';
            const options = Array.from(select.options);
            options.forEach(function(option, index) {
                const customOption = document.createElement('div');
                customOption.className = 'custom-select-option';
                if (option.selected) {
                    customOption.classList.add('selected');
                }
                
                const check = document.createElement('span');
                check.className = 'option-check';
                check.innerHTML = '<i class="fas fa-check"></i>';
                
                const text = document.createElement('span');
                text.className = 'option-text';
                text.textContent = option.text;
                
                customOption.appendChild(check);
                customOption.appendChild(text);
                
                customOption.addEventListener('click', function(e) {
                    e.stopPropagation();
                    
                    // Update native select
                    select.selectedIndex = index;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    
                    // Update custom select
                    updateCustomSelect(select, customSelect, dropdown);
                    
                    // Close dropdown
                    closeDropdown(customSelect, dropdown);
                });
                
                dropdown.appendChild(customOption);
            });
        }
        
        // Initial population
        populateDropdown();
        
        // Listen for programmatic changes to the select
        select.addEventListener('change', function() {
            updateCustomSelect(select, customSelect, dropdown);
        });
        
        // Watch for option changes and rebuild dropdown if needed
        const optionObserver = new MutationObserver(function() {
            populateDropdown();
            updateCustomSelect(select, customSelect, dropdown);
        });
        
        optionObserver.observe(select, { childList: true, subtree: true });
        
        // Insert wrapper before select
        select.parentNode.insertBefore(wrapper, select);
        
        // Move select into wrapper (but keep it hidden)
        wrapper.appendChild(select);
        wrapper.appendChild(customSelect);
        wrapper.appendChild(dropdown);
        
        // Initialize display
        if (select.id === 'general_theme') {
            const currentTheme = document.body.dataset.theme;
            if (currentTheme && Array.from(select.options).some(opt => opt.value === currentTheme)) {
                select.value = currentTheme;
            }
        }
        updateCustomSelect(select, customSelect, dropdown);
        
        // Toggle dropdown
        customSelect.addEventListener('click', function(e) {
            e.stopPropagation();
            const isOpen = customSelect.classList.contains('open');
            
            // Close all other dropdowns
            closeAllDropdowns();

            // Sync specialized selects before opening
            if (select.id === 'general_theme') {
                const currentTheme = document.body.dataset.theme;
                if (currentTheme) {
                    const matchingOption = Array.from(select.options).find(option => option.value === currentTheme);
                    if (matchingOption && select.value !== currentTheme) {
                        select.value = currentTheme;
                        updateCustomSelect(select, customSelect, dropdown);
                    }
                }
            }
            
            if (!isOpen) {
                openDropdown(customSelect, dropdown);
            }
        });
        
        // Close on outside click
        document.addEventListener('click', function(e) {
            // If dropdown is portaled to body, clicks inside dropdown should not count as "outside"
            if (!wrapper.contains(e.target) && !dropdown.contains(e.target)) {
                closeDropdown(customSelect, dropdown);
            }
        });
        
        // Handle keyboard navigation
        customSelect.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const isOpen = customSelect.classList.contains('open');
                if (!isOpen) {
                    openDropdown(customSelect, dropdown);
                }
            } else if (e.key === 'Escape') {
                closeDropdown(customSelect, dropdown);
            }
        });
        
        dropdown.addEventListener('keydown', function(e) {
            const options = Array.from(dropdown.querySelectorAll('.custom-select-option'));
            const currentIndex = options.findIndex(opt => opt.classList.contains('selected'));
            let newIndex = currentIndex;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                newIndex = (currentIndex + 1) % options.length;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                newIndex = currentIndex <= 0 ? options.length - 1 : currentIndex - 1;
            } else if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (currentIndex >= 0) {
                    options[currentIndex].click();
                }
                return;
            } else if (e.key === 'Escape') {
                e.preventDefault();
                closeDropdown(customSelect, dropdown);
                return;
            }
            
            if (newIndex !== currentIndex) {
                options.forEach(opt => opt.classList.remove('selected'));
                options[newIndex].classList.add('selected');
                scrollOptionIntoDropdownView(dropdown, options[newIndex]);
            }
        });

        // Allow external syncs without triggering change events
        select.addEventListener('custom-select:sync', function() {
            updateCustomSelect(select, customSelect, dropdown);
        });
    }

    function updateCustomSelect(select, customSelect, dropdown) {
        const selectedOption = select.options[select.selectedIndex];
        const selectValue = customSelect.querySelector('.select-value');
        
        if (selectedOption) {
            selectValue.textContent = selectedOption.text;
        }
        
        // Update selected state in dropdown
        const options = dropdown.querySelectorAll('.custom-select-option');
        options.forEach(function(option, index) {
            if (index === select.selectedIndex) {
                option.classList.add('selected');
            } else {
                option.classList.remove('selected');
            }
        });
    }

    function scrollOptionIntoDropdownView(dropdown, optionEl) {
        if (!dropdown || !optionEl) return;

        // Only scroll the dropdown itself (avoid scrollIntoView(), which can scroll ancestor containers)
        const optionTop = optionEl.offsetTop;
        const optionBottom = optionTop + optionEl.offsetHeight;
        const viewTop = dropdown.scrollTop;
        const viewBottom = viewTop + dropdown.clientHeight;

        if (optionTop < viewTop) {
            dropdown.scrollTop = optionTop;
        } else if (optionBottom > viewBottom) {
            dropdown.scrollTop = Math.max(0, optionBottom - dropdown.clientHeight);
        }
    }

    function openDropdown(customSelect, dropdown) {
        customSelect.classList.add('open');
        dropdown.classList.add('open');

        // Portal dropdown to body so it isn't clipped by scroll containers (e.g. PDF upload grid).
        portalDropdownToBody(customSelect, dropdown);
        positionPortaledDropdown(customSelect, dropdown);
        
        // Scroll selected option into view
        const selectedOption = dropdown.querySelector('.custom-select-option.selected');
        if (selectedOption) {
            scrollOptionIntoDropdownView(dropdown, selectedOption);
        }
    }

    function closeDropdown(customSelect, dropdown) {
        customSelect.classList.remove('open');
        dropdown.classList.remove('open');
        unportalDropdown(customSelect, dropdown);
    }

    function closeAllDropdowns() {
        const openDropdowns = document.querySelectorAll('.custom-select.open');
        openDropdowns.forEach(function(customSelect) {
            const dropdown = customSelect._customSelectDropdown || customSelect.nextElementSibling;
            if (dropdown) closeDropdown(customSelect, dropdown);
        });
    }

    function portalDropdownToBody(customSelect, dropdown) {
        if (!customSelect || !dropdown) return;
        if (dropdown._portaled) return;

        dropdown._originalParent = dropdown.parentNode;
        dropdown._originalNextSibling = dropdown.nextSibling;
        dropdown._portaled = true;

        dropdown.classList.add('portaled');
        dropdown.style.position = 'absolute';
        dropdown.style.zIndex = '5000';
        dropdown.style.left = '0px';
        dropdown.style.top = '0px';
        dropdown.style.width = 'auto';

        document.body.appendChild(dropdown);

        // Reposition while scrolling/resizing (capture scroll from nested containers too)
        const reposition = () => {
            if (!dropdown._portaled || !customSelect.classList.contains('open')) return;
            positionPortaledDropdown(customSelect, dropdown);
        };
        dropdown._repositionHandler = reposition;
        window.addEventListener('scroll', reposition, true);
        window.addEventListener('resize', reposition);
    }

    function unportalDropdown(customSelect, dropdown) {
        if (!dropdown || !dropdown._portaled) return;
        dropdown._portaled = false;

        dropdown.classList.remove('portaled');
        dropdown.style.left = '';
        dropdown.style.top = '';
        dropdown.style.width = '';
        dropdown.style.position = '';
        dropdown.style.zIndex = '';

        if (dropdown._repositionHandler) {
            window.removeEventListener('scroll', dropdown._repositionHandler, true);
            window.removeEventListener('resize', dropdown._repositionHandler);
            dropdown._repositionHandler = null;
        }

        const parent = dropdown._originalParent;
        if (parent) {
            if (dropdown._originalNextSibling && dropdown._originalNextSibling.parentNode === parent) {
                parent.insertBefore(dropdown, dropdown._originalNextSibling);
            } else {
                parent.appendChild(dropdown);
            }
        }
        dropdown._originalParent = null;
        dropdown._originalNextSibling = null;
    }

    function positionPortaledDropdown(customSelect, dropdown) {
        if (!customSelect || !dropdown) return;
        const rect = customSelect.getBoundingClientRect();
        const scrollX = window.scrollX || window.pageXOffset || 0;
        const scrollY = window.scrollY || window.pageYOffset || 0;

        // Match control width
        dropdown.style.width = `${rect.width}px`;

        // Default: open downward
        let top = rect.bottom + scrollY;

        // If it would go off-screen, try opening upward
        const viewportSpaceBelow = window.innerHeight - rect.bottom;
        const maxHeight = parseInt(getComputedStyle(dropdown).maxHeight || '300', 10) || 300;
        if (viewportSpaceBelow < Math.min(maxHeight, 180) && rect.top > 180) {
            top = rect.top + scrollY - Math.min(dropdown.scrollHeight || maxHeight, maxHeight);
        }

        dropdown.style.left = `${rect.left + scrollX}px`;
        dropdown.style.top = `${top}px`;
    }
})();

