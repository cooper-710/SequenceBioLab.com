document.addEventListener('DOMContentLoaded', function () {
    var scheduleContainer = document.getElementById('gameday-schedule-content');
    var leadersContainer = document.getElementById('gameday-leaders-content');
    var standingsContainer = document.getElementById('gameday-standings-content');
    var leaderSelects = [];
    var standingForms = document.querySelectorAll('.standings-form');
    var standingsSelects = document.querySelectorAll('.standings-select');
    var standingsTabs = document.querySelectorAll('.standings-tab');
    var docsList = document.querySelector('.player-docs-list');
    var docsCountPill = document.querySelector('.docs-count-pill');
    var docsEmptyPlaceholder = document.querySelector('.docs-empty-placeholder');
    var currentScheduleBucket = 'current';
    var currentScheduleOpponent = '';

    function filterPlayerDocs(bucket, opponent) {
        if (!docsList) {
            return;
        }
        var items = docsList.querySelectorAll('.player-docs-item');
        if (!items.length) {
            if (docsCountPill) {
                docsCountPill.textContent = '0 files';
            }
            if (docsEmptyPlaceholder) {
                docsEmptyPlaceholder.hidden = false;
            }
            return;
        }
        var targetBucket = bucket || '';
        var opponentKey = (opponent || '').toLowerCase();
        var visible = 0;
        items.forEach(function (item) {
            var status = (item.dataset.docStatus || 'none').toLowerCase();
            var docOpp = (item.dataset.docOpponent || '').toLowerCase();
            var shouldShow = false;
            if (status === 'none') {
                shouldShow = true;
            } else if (targetBucket === 'current') {
                shouldShow = status === 'current' && (!opponentKey || docOpp === opponentKey);
            } else if (targetBucket === 'future') {
                shouldShow = status === 'upcoming' && (!opponentKey || docOpp === opponentKey);
            } else if (targetBucket === 'past') {
                shouldShow = status === 'expired' && (!opponentKey || docOpp === opponentKey);
            }
            item.hidden = !shouldShow;
            item.style.display = shouldShow ? '' : 'none';
            if (shouldShow) {
                visible += 1;
            }
        });
        if (docsCountPill) {
            docsCountPill.textContent = visible + ' ' + (visible === 1 ? 'file' : 'files');
        }
        if (docsEmptyPlaceholder) {
            docsEmptyPlaceholder.hidden = visible > 0;
        }
    }

    function loadGamedayWidgets() {
        if (!leadersContainer) {
            return;
        }

        var endpoint = leadersContainer.dataset.widgetsEndpoint;
        if (!endpoint) {
            return;
        }

        var params = new URLSearchParams(window.location.search || "");
        var url = endpoint + (params.toString() ? ("?" + params.toString()) : "");

        var controller = null;
        var timeoutId = null;
        try {
            controller = new AbortController();
            timeoutId = setTimeout(function () {
                controller.abort();
            }, 4500);
        } catch (err) {
            controller = null;
        }

        fetch(url, controller ? { signal: controller.signal, headers: { "Accept": "application/json" } } : { headers: { "Accept": "application/json" } })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (payload) {
                if (!payload) {
                    return;
                }
                if (typeof payload.leaders_html === "string" && leadersContainer) {
                    leadersContainer.innerHTML = payload.leaders_html;
                }
                if (typeof payload.standings_html === "string" && standingsContainer) {
                    standingsContainer.innerHTML = payload.standings_html;
                }
                initLeaderControls();
                requestAnimationFrame(syncLeaderHeights);
            })
            .catch(function () {
                // Keep placeholders if the widget request fails.
            })
            .finally(function () {
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }
            });
    }

    function autoHideRedirectNote() {
        var redirectNote = document.querySelector('.schedule-redirect-note');
        if (!redirectNote) {
            return;
        }
        setTimeout(function() {
            redirectNote.style.transition = 'opacity 0.5s ease-out';
            redirectNote.style.opacity = '0';
            setTimeout(function() {
                redirectNote.style.display = 'none';
            }, 500);
        }, 5000);
    }

    function initScheduleAndDocs() {
        var scheduleCard = document.querySelector('.schedule-card');
        if (scheduleCard) {
        var scheduleTabs = scheduleCard.querySelectorAll('.schedule-tab');
        var scheduleList = scheduleCard.querySelector('.matchups-list');
        var scheduleEmpty = scheduleCard.querySelector('.schedule-empty');

        if (scheduleList) {
            var scheduleItems = scheduleList.querySelectorAll('li');
            var scheduleBucketPrimaryOpp = {};
            var scheduleBucketLabels = {
                past: 'past series',
                current: 'current series',
                future: 'upcoming series'
            };

            var categorize = function (item) {
                // Use category from data attribute if available (from backend)
                var category = item.dataset.category;
                if (category && ['past', 'current', 'future'].includes(category)) {
                    return category;
                }
                // Fallback to status-based categorization
                var status = (item.dataset.status || '').toLowerCase();
                if (status.includes('final') || status.includes('game over')) {
                    return 'past';
                }
                if (
                    status.includes('in progress') ||
                    status.includes('pre-game') ||
                    status.includes('pregame') ||
                    status.includes('pre game') ||
                    status.includes('delayed')
                ) {
                    return 'current';
                }
                return 'future';
            };

            scheduleItems.forEach(function (item) {
                item.dataset.bucket = categorize(item);
                var bucket = item.dataset.bucket;
                if (!scheduleBucketPrimaryOpp[bucket]) {
                    scheduleBucketPrimaryOpp[bucket] = item.dataset.opponent || '';
                }
            });

            var applyScheduleFilter = function (bucket) {
                var visibleCount = 0;
                scheduleCard.dataset.scheduleState = bucket;

                scheduleTabs.forEach(function (tab) {
                    var isActive = tab.dataset.filter === bucket;
                    tab.classList.toggle('is-active', isActive);
                    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
                });

                // Find all items in this bucket and show only the first (next) one
                var itemsInBucket = [];
                scheduleItems.forEach(function (item) {
                    if (item.dataset.bucket === bucket) {
                        itemsInBucket.push(item);
                    }
                });

                // Show only the first series in each category
                var firstItem = itemsInBucket.length > 0 ? itemsInBucket[0] : null;
                var primaryOpponent = firstItem ? (firstItem.dataset.opponent || '') : '';

                scheduleItems.forEach(function (item) {
                    var inBucket = item.dataset.bucket === bucket;
                    // Only show the first item in the bucket
                    var shouldShow = inBucket && item === firstItem;
                    item.hidden = !shouldShow;
                    item.style.display = shouldShow ? '' : 'none';
                    if (shouldShow) {
                        visibleCount += 1;
                    }
                });

                if (scheduleList) {
                    scheduleList.hidden = visibleCount === 0;
                }

                if (scheduleEmpty) {
                    if (visibleCount > 0) {
                        scheduleEmpty.hidden = true;
                    } else {
                        scheduleEmpty.hidden = false;
                        scheduleEmpty.textContent = 'No ' + (scheduleBucketLabels[bucket] || 'series') + ' in this view yet.';
                    }
                }

                currentScheduleBucket = bucket;
                currentScheduleOpponent = primaryOpponent || '';
                filterPlayerDocs(currentScheduleBucket, currentScheduleOpponent);
            };

            scheduleTabs.forEach(function (tab) {
                tab.addEventListener('click', function () {
                    applyScheduleFilter(tab.dataset.filter);
                });
            });

            if (scheduleItems.length > 0) {
                // Use the default tab from the template if available
                var defaultTab = scheduleCard.dataset.scheduleState || 'current';
                applyScheduleFilter(defaultTab);
                
                // If no items are visible with the default tab, try other tabs
                var hasVisibleItems = Array.prototype.some.call(scheduleItems, function (item) {
                    return !item.hidden;
                });
                if (!hasVisibleItems) {
                    var defaultBuckets = ['current', 'future', 'past'];
                    var applied = defaultBuckets.some(function (bucket) {
                        applyScheduleFilter(bucket);
                        return Array.prototype.some.call(scheduleItems, function (item) {
                            return !item.hidden;
                        });
                    });
                    if (!applied) {
                        applyScheduleFilter('future');
                    }
                }
            }
        } else {
            scheduleTabs.forEach(function (tab) {
                tab.setAttribute('aria-disabled', 'true');
            });
            if (scheduleEmpty) {
                scheduleEmpty.hidden = true;
            }
            currentScheduleBucket = 'current';
            currentScheduleOpponent = '';
            filterPlayerDocs(currentScheduleBucket, currentScheduleOpponent);
        }
    }
    }

    function syncLeaderHeights() {
        var visibleCards = [];
        document.querySelectorAll('.leaders-card').forEach(function (card) {
            if (card.classList.contains('is-hidden')) {
                card.style.minHeight = '';
            } else {
                card.style.minHeight = '';
                visibleCards.push(card);
            }
        });

        var maxHeight = 0;
        visibleCards.forEach(function (card) {
            maxHeight = Math.max(maxHeight, card.offsetHeight);
        });

        if (maxHeight) {
            document.querySelectorAll('.leaders-grid').forEach(function (grid) {
                grid.style.minHeight = maxHeight + 'px';
            });
        } else {
            document.querySelectorAll('.leaders-grid').forEach(function (grid) {
                grid.style.minHeight = '';
            });
        }
    }

    function initLeaderControls() {
        leaderSelects = document.querySelectorAll('.leaders-select');
        leaderSelects.forEach(function (select) {
            var group = select.dataset.group;
            select.addEventListener('change', function () {
                var selected = select.value;
                document.querySelectorAll('.leaders-card[data-group="' + group + '"]').forEach(function (card) {
                    card.classList.toggle('is-hidden', card.dataset.category !== selected);
                });
                requestAnimationFrame(syncLeaderHeights);
            });
        });
        requestAnimationFrame(syncLeaderHeights);
    }

    function loadGamedaySchedule() {
        if (!scheduleContainer) {
            return;
        }
        var endpoint = scheduleContainer.dataset.scheduleEndpoint;
        if (!endpoint) {
            return;
        }
        var params = new URLSearchParams(window.location.search || "");
        var url = endpoint + (params.toString() ? ("?" + params.toString()) : "");

        fetch(url, { headers: { "Accept": "application/json" } })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (payload) {
                if (!payload || typeof payload.schedule_html !== "string") {
                    return;
                }
                scheduleContainer.innerHTML = payload.schedule_html;
                autoHideRedirectNote();
                initScheduleAndDocs();
            })
            .catch(function () {
                // Keep placeholder if schedule request fails
            });
    }

    window.addEventListener('resize', function () {
        requestAnimationFrame(syncLeaderHeights);
    });

    // Kick off async loads immediately (before heavy DOM work)
    loadGamedayWidgets();
    loadGamedaySchedule();

    initLeaderControls();
    initScheduleAndDocs();

    function markScrollIntent() {
        try {
            sessionStorage.setItem('scrollToStandings', '1');
        } catch (err) {
            // storage may be unavailable; ignore
        }
    }

    standingForms.forEach(function (form) {
        form.addEventListener('submit', markScrollIntent);
    });

    standingsSelects.forEach(function (select) {
        select.addEventListener('change', markScrollIntent, { passive: true });
    });

    standingsTabs.forEach(function (tab) {
        tab.addEventListener('click', markScrollIntent, { passive: true });
    });

    var shouldScroll = false;
    try {
        shouldScroll = sessionStorage.getItem('scrollToStandings') === '1';
        sessionStorage.removeItem('scrollToStandings');
    } catch (err) {
        shouldScroll = false;
    }

    if (shouldScroll) {
        var standings = document.getElementById('standings');
        if (standings) {
            var scrollToStandings = function () {
                standings.scrollIntoView({ behavior: 'instant', block: 'start' });
            };
            requestAnimationFrame(function () {
                requestAnimationFrame(scrollToStandings);
            });
        }
    }
});