# Issues Report - SequenceBioLab Project

**Date:** November 13, 2025  
**Status:** Comprehensive Review Complete

## Summary

I've conducted a thorough review of the entire project repository, tested the application in a browser, and identified several issues that should be addressed. The application runs successfully, but there are configuration, consistency, and potential runtime issues.

---

## 🔴 Critical Issues

### 1. **Incorrect Data Directory Path in settings.json**
**Location:** `config/settings.json`  
**Issue:** The `data_directory` setting points to a non-existent path:
```json
"data_directory": "/Users/cooperrobinson/Desktop/Projects/Scouting Report/data"
```
**Actual project location:** `/Users/cooperrobinson/Desktop/SequenceBioLab-main/data`

**Impact:** 
- Any code that uses the `data_directory` setting from settings.json will fail
- The CSV data loader currently works because it uses a hardcoded path relative to ROOT_DIR, but if any code tries to use the settings value, it will break

**Recommendation:** Update the path to use a relative path or the correct absolute path:
```json
"data_directory": "./data"
```
or
```json
"data_directory": "/Users/cooperrobinson/Desktop/SequenceBioLab-main/data"
```

---

## 🟡 Configuration Inconsistencies

### 2. **Settings Schema Mismatch**
**Location:** `config/settings.json` vs `config/settings.json.example` and `settings_manager.py`

**Issue:** 
- `settings.json` contains `"sportradar_api_key"` in the integrations section
- `settings.json.example` does NOT include this field
- `settings_manager.py` DEFAULT_SETTINGS does NOT include this field

**Impact:** 
- The field exists in the actual settings but not in defaults, which could cause issues when settings are reset or merged
- Code that references this setting may not work as expected

**Recommendation:** 
- Add `"sportradar_api_key": ""` to `settings_manager.py` DEFAULT_SETTINGS
- Add it to `settings.json.example` for consistency

### 3. **Missing Settings Field in Example**
**Location:** `config/settings.json.example`  
**Issue:** The example file is missing the `secret_key` field that exists in the actual settings.json

**Impact:** New installations won't have this field documented

**Recommendation:** Add `"secret_key": ""` to the example file (or document that it's auto-generated)

---

## 🟢 Minor Issues & Observations

### 4. **Hardcoded Default Team**
**Location:** `app.py` line ~894  
**Issue:** The `_determine_user_team()` function has a hardcoded default of "NYM" (New York Mets)

```python
if not team_abbr or team_abbr == "AUTO":
    team_abbr = "NYM"  # sensible default
```

**Impact:** All users without a team setting will default to NYM, which may not be appropriate for all use cases

**Recommendation:** Make this configurable via settings or environment variable

### 5. **CSV Data Loader Path Handling**
**Location:** `src/csv_data_loader.py`  
**Observation:** The CSVDataLoader uses hardcoded relative paths from ROOT_DIR instead of respecting the `data_directory` setting from settings.json

**Impact:** The settings.json `data_directory` value is effectively ignored by the CSV loader

**Recommendation:** Update CSVDataLoader to optionally use the settings value if provided

### 6. **Missing Error Handling for Missing CSV Files**
**Location:** `src/csv_data_loader.py`  
**Observation:** The loader gracefully handles missing files by returning None, but there's no user-facing error message if all CSV files are missing

**Impact:** Users might not realize why player data isn't loading

**Recommendation:** Add logging or user-facing warnings when CSV files are missing

### 7. **Port Selection Logic**
**Location:** `app.py` lines 10675-10680  
**Observation:** The app starts on port 5001 by default, but the find_free_port function starts searching from 5001, which means it will always use 5001 if available

**Impact:** Minor - the comment says "Start from 5001 to match browser config" but it's not clear what browser config this refers to

**Recommendation:** Document why port 5001 is preferred, or make it configurable

### 8. **Session Management**
**Observation:** The application appears to maintain sessions across restarts (user was already logged in when testing)

**Impact:** This could be a security concern if sessions aren't properly invalidated

**Recommendation:** Verify session persistence behavior and ensure proper session management

---

## ✅ Positive Findings

1. **All Dependencies Installed:** All required packages (Flask, pandas, numpy, statsapi, etc.) are properly installed
2. **Templates Present:** All 42 template files referenced in the code exist
3. **Static Files Present:** Required static files (logos, CSS, JS) are in place
4. **Database Schema:** Database initialization includes proper migration logic for adding new columns
5. **Error Handling:** Good use of try/except blocks for optional imports
6. **CSRF Protection:** CSRF tokens are implemented for form submissions
7. **Security:** Password hashing is properly implemented using werkzeug

---

## 🔍 Testing Results

### Application Startup
- ✅ Application starts successfully
- ✅ No import errors
- ✅ Database initializes correctly
- ✅ CSV data loader initializes successfully
- ✅ Server runs on port 5001

### Browser Testing
- ✅ Login page loads correctly
- ✅ Home page accessible (user was already authenticated)
- ✅ No JavaScript console errors observed
- ✅ Navigation appears functional

---

## 📋 Recommendations Summary

### Immediate Actions:
1. **Fix data_directory path** in `config/settings.json`
2. **Add sportradar_api_key** to DEFAULT_SETTINGS in `settings_manager.py`
3. **Update settings.json.example** to match actual settings structure

### Future Improvements:
1. Make default team configurable
2. Update CSVDataLoader to respect settings.json data_directory
3. Add better error messages for missing data files
4. Document port selection logic
5. Review session persistence behavior

---

## 📝 Notes

- The application is functional and appears to be in active development
- Most issues are configuration-related rather than code bugs
- The codebase is well-structured with good separation of concerns
- Error handling is generally good, but could be improved in some areas

---

**Review Completed By:** AI Assistant  
**Review Method:** Code analysis, dependency checking, runtime testing, browser testing





