(() => {
    const panel = document.querySelector('[data-weather-panel]');
    if (!panel) {
        return;
    }

    const weatherPanel = panel.querySelector('.weather-panel');
    const snowTarget = weatherPanel || panel;
    const weatherEndpoint = panel.dataset.weatherEndpoint;

    const iconEl = panel.querySelector('[data-weather-icon] i');
    const tempEl = panel.querySelector('[data-weather-temp]');
    const descEl = panel.querySelector('[data-weather-desc]');
    const locationEl = panel.querySelector('[data-weather-location]');
    const timeEl = panel.querySelector('[data-weather-time]') || document.querySelector('[data-weather-time]');
    const sunriseEl = panel.querySelector('[data-sunrise]');
    const sunsetEl = panel.querySelector('[data-sunset]');
    const phaseEl = panel.querySelector('[data-phase-label]');
    const phaseIconEl = panel.querySelector('[data-weather-phase] i');

    const temperatureUnit = 'celsius';
    const temperatureLabel = 'C';

    const themeClasses = [
        'weather-theme--sun',
        'weather-theme--snow',
        'weather-theme--rain',
        'weather-theme--cloud',
        'weather-theme--storm',
        'weather-theme--night',
    ];
    const phaseClasses = ['weather-phase--day', 'weather-phase--night'];

    const snowCodes = new Set([71, 73, 75, 77, 85, 86]);
    const rainCodes = new Set([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]);
    const stormCodes = new Set([95, 96, 99]);
    const fogCodes = new Set([45, 48]);

    const themeTargets = [panel];
    const setTheme = (theme) => {
        themeTargets.forEach((target) => target.classList.remove(...themeClasses));
        if (!theme) {
            return;
        }
        const themeClass = `weather-theme--${theme}`;
        themeTargets.forEach((target) => target.classList.add(themeClass));
    };

    const setPhase = (isDay) => {
        themeTargets.forEach((target) => target.classList.remove(...phaseClasses));
        const phaseClass = isDay ? 'weather-phase--day' : 'weather-phase--night';
        themeTargets.forEach((target) => target.classList.add(phaseClass));
    };

    const setIcon = (el, iconClass) => {
        if (!el || !iconClass) {
            return;
        }
        el.className = `fas ${iconClass}`;
    };

    const extractTime = (value) => {
        if (!value) {
            return null;
        }
        const parts = value.split('T');
        return parts.length > 1 ? parts[1] : parts[0];
    };

    const formatTimeValue = (value) => {
        const timePart = extractTime(value);
        if (!timePart) {
            return '--:--';
        }
        const pieces = timePart.split(':');
        if (pieces.length < 2) {
            return timePart;
        }
        const hour = Number.parseInt(pieces[0], 10);
        const minute = Number.parseInt(pieces[1], 10);
        if (Number.isNaN(hour) || Number.isNaN(minute)) {
            return timePart;
        }
        const period = hour >= 12 ? 'PM' : 'AM';
        const hour12 = hour % 12 || 12;
        return `${hour12}:${minute.toString().padStart(2, '0')} ${period}`;
    };

    const timeToMinutes = (value) => {
        const timePart = extractTime(value);
        if (!timePart) {
            return null;
        }
        const pieces = timePart.split(':');
        if (pieces.length < 2) {
            return null;
        }
        const hour = Number.parseInt(pieces[0], 10);
        const minute = Number.parseInt(pieces[1], 10);
        if (Number.isNaN(hour) || Number.isNaN(minute)) {
            return null;
        }
        return hour * 60 + minute;
    };

    const describeWeather = (code, isDay) => {
        if (snowCodes.has(code)) {
            return { label: 'Snow', icon: 'fa-snowflake', theme: 'snow' };
        }
        if (stormCodes.has(code)) {
            return { label: 'Thunder', icon: 'fa-bolt', theme: 'storm' };
        }
        if (rainCodes.has(code)) {
            return { label: 'Rain', icon: 'fa-cloud-rain', theme: 'rain' };
        }
        if (fogCodes.has(code)) {
            return { label: 'Fog', icon: 'fa-smog', theme: 'cloud' };
        }
        if (code === 2) {
            return {
                label: 'Partly cloudy',
                icon: isDay ? 'fa-cloud-sun' : 'fa-cloud-moon',
                theme: 'cloud',
            };
        }
        if (code === 3) {
            return { label: 'Overcast', icon: 'fa-cloud', theme: 'cloud' };
        }
        if (code === 1) {
            return {
                label: 'Mostly clear',
                icon: isDay ? 'fa-sun' : 'fa-moon',
                theme: isDay ? 'sun' : 'night',
            };
        }
        if (code === 0) {
            return {
                label: 'Clear',
                icon: isDay ? 'fa-sun' : 'fa-moon',
                theme: isDay ? 'sun' : 'night',
            };
        }
        return {
            label: 'Weather',
            icon: isDay ? 'fa-cloud-sun' : 'fa-cloud-moon',
            theme: isDay ? 'sun' : 'night',
        };
    };

    const normalizeSnowfall = (value, units) => {
        const amount = Number(value);
        if (!Number.isFinite(amount)) {
            return null;
        }
        const unit = (units || '').toLowerCase();
        if (unit.includes('cm')) {
            return amount;
        }
        if (unit.includes('mm')) {
            return amount / 10;
        }
        if (unit.includes('inch') || unit.includes('in')) {
            return amount * 2.54;
        }
        return amount;
    };

    const mapSnowfallToStyle = (amountCm) => {
        if (amountCm <= 0) {
            return {
                opacity: '0.35',
                speed: '26s',
                size1: '18px',
                size2: '24px',
                size3: '32px',
                size4: '40px',
                blur: '0.05px',
            };
        }
        if (amountCm < 0.2) {
            return {
                opacity: '0.45',
                speed: '22s',
                size1: '17px',
                size2: '23px',
                size3: '30px',
                size4: '38px',
                blur: '0.08px',
            };
        }
        if (amountCm < 0.5) {
            return {
                opacity: '0.6',
                speed: '18s',
                size1: '16px',
                size2: '22px',
                size3: '28px',
                size4: '36px',
                blur: '0.1px',
            };
        }
        if (amountCm < 1.0) {
            return {
                opacity: '0.75',
                speed: '14s',
                size1: '15px',
                size2: '20px',
                size3: '26px',
                size4: '34px',
                blur: '0.12px',
            };
        }
        if (amountCm < 2.0) {
            return {
                opacity: '0.88',
                speed: '11s',
                size1: '14px',
                size2: '19px',
                size3: '24px',
                size4: '32px',
                blur: '0.15px',
            };
        }
        return {
            opacity: '0.95',
            speed: '8s',
            size1: '12px',
            size2: '17px',
            size3: '22px',
            size4: '28px',
            blur: '0.18px',
        };
    };

    const clearSnowStyle = () => {
        if (!snowTarget) {
            return;
        }
        snowTarget.style.removeProperty('--snow-opacity');
        snowTarget.style.removeProperty('--snow-speed');
        snowTarget.style.removeProperty('--snow-size-1');
        snowTarget.style.removeProperty('--snow-size-2');
        snowTarget.style.removeProperty('--snow-size-3');
        snowTarget.style.removeProperty('--snow-size-4');
        snowTarget.style.removeProperty('--snow-blur');
    };

    const applySnowIntensity = (amountCm, isSnowTheme) => {
        if (!snowTarget) {
            return;
        }
        if (!isSnowTheme) {
            clearSnowStyle();
            return;
        }
        let resolved = amountCm;
        if (!Number.isFinite(resolved) && isSnowTheme) {
            resolved = 0.2;
        }
        if (!Number.isFinite(resolved)) {
            clearSnowStyle();
            return;
        }
        const style = mapSnowfallToStyle(Math.max(0, resolved));
        snowTarget.style.setProperty('--snow-opacity', style.opacity);
        snowTarget.style.setProperty('--snow-speed', style.speed);
        snowTarget.style.setProperty('--snow-size-1', style.size1);
        snowTarget.style.setProperty('--snow-size-2', style.size2);
        snowTarget.style.setProperty('--snow-size-3', style.size3);
        snowTarget.style.setProperty('--snow-size-4', style.size4);
        snowTarget.style.setProperty('--snow-blur', style.blur);
    };

    const normalizeAddress = (value) => (value || '').replace(/\s+/g, ' ').trim();

    const provinceNameMap = {
        AB: 'Alberta',
        BC: 'British Columbia',
        MB: 'Manitoba',
        NB: 'New Brunswick',
        NL: 'Newfoundland and Labrador',
        NT: 'Northwest Territories',
        NS: 'Nova Scotia',
        NU: 'Nunavut',
        ON: 'Ontario',
        PE: 'Prince Edward Island',
        QC: 'Quebec',
        SK: 'Saskatchewan',
        YT: 'Yukon',
    };

    const usStateNames = {
        AL: 'Alabama',
        AK: 'Alaska',
        AZ: 'Arizona',
        AR: 'Arkansas',
        CA: 'California',
        CO: 'Colorado',
        CT: 'Connecticut',
        DE: 'Delaware',
        FL: 'Florida',
        GA: 'Georgia',
        HI: 'Hawaii',
        ID: 'Idaho',
        IL: 'Illinois',
        IN: 'Indiana',
        IA: 'Iowa',
        KS: 'Kansas',
        KY: 'Kentucky',
        LA: 'Louisiana',
        ME: 'Maine',
        MD: 'Maryland',
        MA: 'Massachusetts',
        MI: 'Michigan',
        MN: 'Minnesota',
        MS: 'Mississippi',
        MO: 'Missouri',
        MT: 'Montana',
        NE: 'Nebraska',
        NV: 'Nevada',
        NH: 'New Hampshire',
        NJ: 'New Jersey',
        NM: 'New Mexico',
        NY: 'New York',
        NC: 'North Carolina',
        ND: 'North Dakota',
        OH: 'Ohio',
        OK: 'Oklahoma',
        OR: 'Oregon',
        PA: 'Pennsylvania',
        RI: 'Rhode Island',
        SC: 'South Carolina',
        SD: 'South Dakota',
        TN: 'Tennessee',
        TX: 'Texas',
        UT: 'Utah',
        VT: 'Vermont',
        VA: 'Virginia',
        WA: 'Washington',
        WV: 'West Virginia',
        WI: 'Wisconsin',
        WY: 'Wyoming',
    };

    const normalizeKey = (value) => normalizeAddress(value).toLowerCase();

    const formatLocation = (city, province) => {
        const cityValue = normalizeAddress(city);
        const provinceValue = normalizeAddress(province);
        if (cityValue && provinceValue && normalizeKey(cityValue) !== normalizeKey(provinceValue)) {
            return `${cityValue}, ${provinceValue}`;
        }
        return cityValue || provinceValue || '';
    };

    const extractPostal = (address) => {
        if (!address) {
            return '';
        }
        const canadaMatch = address.match(/[A-Z]\d[A-Z]\s?\d[A-Z]\d/i);
        if (canadaMatch) {
            return canadaMatch[0].toUpperCase().replace(/\s+/g, ' ');
        }
        const usMatch = address.match(/\b\d{5}(?:-\d{4})?\b/);
        if (usMatch) {
            return usMatch[0];
        }
        return '';
    };

    const extractProvince = (address) => {
        if (!address) {
            return '';
        }
        const match = address.match(/\b[A-Z]{2}\b/);
        if (!match) {
            return '';
        }
        const code = match[0].toUpperCase();
        if (provinceNameMap[code] || usStateNames[code]) {
            return code;
        }
        return '';
    };

    const extractCity = (address) => {
        if (!address) {
            return '';
        }
        const parts = address.split(',').map((part) => normalizeAddress(part)).filter(Boolean);
        if (parts.length >= 2) {
            return parts[1];
        }
        return '';
    };

    const buildStoreAddress = (dataset) => {
        const addressValue = normalizeAddress(dataset.storeAddress);
        if (addressValue) {
            return addressValue;
        }
        const street = normalizeAddress(dataset.storeStreet);
        const city = normalizeAddress(dataset.storeCity);
        const province = normalizeAddress(dataset.storeProvince);
        const postal = normalizeAddress(dataset.storePostal);
        const parts = [];
        if (street) {
            parts.push(street);
        }
        if (city) {
            parts.push(city);
        }
        if (province && (street || city || postal)) {
            parts.push(province);
        }
        if (postal) {
            parts.push(postal);
        }
        return parts.join(', ');
    };

    const buildStoreParts = (dataset) => {
        const addressValue = normalizeAddress(dataset.storeAddress);
        const street = normalizeAddress(dataset.storeStreet) || '';
        const city = normalizeAddress(dataset.storeCity) || extractCity(addressValue);
        const province = normalizeAddress(dataset.storeProvince) || extractProvince(addressValue);
        const postal = normalizeAddress(dataset.storePostal) || extractPostal(addressValue);
        return {
            address: addressValue,
            street,
            city,
            province,
            postal,
        };
    };

    let storeParts = null;

    const weatherCacheVersion = 3;
    const weatherCacheTtlMs = 1000 * 60 * 10;

    const loadCachedWeather = (addressKey) => {
        if (!window.localStorage) {
            return null;
        }
        try {
            const raw = localStorage.getItem(`storefrontWeatherData:${addressKey}`);
            if (!raw) {
                return null;
            }
            const cached = JSON.parse(raw);
            if (!cached || cached.version !== weatherCacheVersion) {
                return null;
            }
            if (!Number.isFinite(cached.timestamp)) {
                return null;
            }
            const ageMs = Date.now() - cached.timestamp;
            if (ageMs > weatherCacheTtlMs) {
                return null;
            }
            return cached;
        } catch (error) {
            return null;
        }
    };

    const storeCachedWeather = (addressKey, snapshot) => {
        if (!window.localStorage) {
            return;
        }
        try {
            localStorage.setItem(
                `storefrontWeatherData:${addressKey}`,
                JSON.stringify({
                    version: weatherCacheVersion,
                    timestamp: Date.now(),
                    ...snapshot,
                }),
            );
        } catch (error) {
            // Ignore cache write errors.
        }
    };

    const loadCachedCoords = (addressKey) => {
        if (!window.localStorage) {
            return null;
        }
        try {
            const raw = localStorage.getItem(`storefrontWeatherCoords:${addressKey}`);
            if (!raw) {
                return null;
            }
            const cached = JSON.parse(raw);
            if (!cached || !cached.latitude || !cached.longitude || !cached.timestamp) {
                return null;
            }
            const ageMs = Date.now() - cached.timestamp;
            if (ageMs > 1000 * 60 * 60 * 24 * 7) {
                return null;
            }
            return cached;
        } catch (error) {
            return null;
        }
    };

    const storeCachedCoords = (addressKey, coords) => {
        if (!window.localStorage) {
            return;
        }
        try {
            const payload = {
                latitude: coords.latitude,
                longitude: coords.longitude,
                timestamp: Date.now(),
            };
            localStorage.setItem(`storefrontWeatherCoords:${addressKey}`, JSON.stringify(payload));
        } catch (error) {
            // Ignore cache write errors.
        }
    };

    const geocodeQuery = async (query) => {
        const params = new URLSearchParams({
            name: query,
            count: '10',
            language: 'en',
            format: 'json',
        });
        const response = await fetch(`https://geocoding-api.open-meteo.com/v1/search?${params.toString()}`);
        if (!response.ok) {
            throw new Error('Geocoding request failed');
        }
        const data = await response.json();
        return data && data.results ? data.results : [];
    };

    const resolveCountryCode = (province) => {
        const code = (province || '').toUpperCase();
        if (provinceNameMap[code]) {
            return 'CA';
        }
        if (usStateNames[code]) {
            return 'US';
        }
        return '';
    };

    const resolveProvinceName = (province) => {
        const code = (province || '').toUpperCase();
        if (provinceNameMap[code]) {
            return provinceNameMap[code];
        }
        if (usStateNames[code]) {
            return usStateNames[code];
        }
        return province || '';
    };

    const pickGeocodeResult = (results, parts) => {
        if (!results || !results.length) {
            return null;
        }
        const countryCode = resolveCountryCode(parts.province);
        const provinceName = normalizeKey(resolveProvinceName(parts.province));
        const cityName = normalizeKey(parts.city);

        let candidates = results;
        if (countryCode) {
            candidates = candidates.filter((item) => item.country_code === countryCode);
        }
        if (provinceName) {
            const provinceMatches = candidates.filter(
                (item) => normalizeKey(item.admin1) === provinceName,
            );
            if (provinceMatches.length) {
                candidates = provinceMatches;
            }
        }
        if (cityName) {
            const cityMatches = candidates.filter(
                (item) => normalizeKey(item.name) === cityName,
            );
            if (cityMatches.length) {
                candidates = cityMatches;
            }
        }
        return candidates[0] || results[0];
    };

    const geocodeStore = async (parts) => {
        const queries = [];
        if (parts.city && parts.province) {
            queries.push(`${parts.city}, ${parts.province}`);
        }
        if (parts.city) {
            queries.push(parts.city);
        }
        if (parts.postal) {
            queries.push(parts.postal);
        }
        if (parts.address) {
            queries.push(parts.address);
        }
        const uniqueQueries = [...new Set(queries.filter(Boolean))];
        for (const query of uniqueQueries) {
            const results = await geocodeQuery(query);
            const picked = pickGeocodeResult(results, parts);
            if (picked && Number.isFinite(picked.latitude) && Number.isFinite(picked.longitude)) {
                return {
                    latitude: picked.latitude,
                    longitude: picked.longitude,
                    city: picked.name || '',
                    province: picked.admin1 || '',
                };
            }
        }
        throw new Error('Geocoding result missing');
    };

    const fetchWeather = async (coords) => {
        const params = new URLSearchParams({
            latitude: coords.latitude.toFixed(4),
            longitude: coords.longitude.toFixed(4),
            current: 'temperature_2m,weathercode,is_day,snowfall,precipitation',
            hourly: 'snowfall',
            daily: 'sunrise,sunset',
            forecast_days: '1',
            timezone: 'auto',
        });
        params.set('temperature_unit', temperatureUnit);
        const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params.toString()}`);
        if (!response.ok) {
            throw new Error('Weather request failed');
        }
        return response.json();
    };

    const findClosestIndex = (times, targetTime) => {
        if (!times || !times.length || !targetTime) {
            return null;
        }
        const targetMs = Date.parse(targetTime);
        if (!Number.isFinite(targetMs)) {
            return null;
        }
        let bestIndex = null;
        let bestDiff = Number.POSITIVE_INFINITY;
        for (let i = 0; i < times.length; i += 1) {
            const timeMs = Date.parse(times[i]);
            if (!Number.isFinite(timeMs)) {
                continue;
            }
            const diff = Math.abs(timeMs - targetMs);
            if (diff < bestDiff) {
                bestDiff = diff;
                bestIndex = i;
            }
        }
        return bestIndex;
    };

    const resolveSnowfallAmount = (data) => {
        const current = data.current || data.current_weather || {};
        if (Number.isFinite(current.snowfall)) {
            return current.snowfall;
        }
        const hourly = data.hourly || {};
        const snow = hourly.snowfall || [];
        const times = hourly.time || [];
        if (!times.length || !snow.length || times.length !== snow.length) {
            return null;
        }
        const targetTime = current.time || times[0];
        const index = findClosestIndex(times, targetTime);
        if (index === null) {
            return null;
        }
        const value = Number(snow[index]);
        return Number.isFinite(value) ? value : null;
    };

    const resolveSnowfallUnits = (data) => {
        return (data.current_units && data.current_units.snowfall)
            || (data.hourly_units && data.hourly_units.snowfall)
            || '';
    };

    const startClock = (timeZone, sunriseValue, sunsetValue, isDayFlag) => {
        if (!timeEl && !phaseEl) {
            return;
        }

        const timeFormatter = new Intl.DateTimeFormat('en-US', {
            timeZone,
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
        });
        const displayFormatter = new Intl.DateTimeFormat('en-US', {
            timeZone,
            weekday: 'short',
            month: 'short',
            day: '2-digit',
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
        });
        const sunriseMinutes = timeToMinutes(sunriseValue);
        const sunsetMinutes = timeToMinutes(sunsetValue);

        const getCurrentMinutes = () => {
            const parts = timeFormatter.formatToParts(new Date());
            const hourPart = parts.find((part) => part.type === 'hour');
            const minutePart = parts.find((part) => part.type === 'minute');
            const dayPeriodPart = parts.find((part) => part.type === 'dayPeriod');
            if (!hourPart || !minutePart) {
                return null;
            }
            let hour = Number.parseInt(hourPart.value, 10);
            const minute = Number.parseInt(minutePart.value, 10);
            if (Number.isNaN(hour) || Number.isNaN(minute)) {
                return null;
            }
            if (dayPeriodPart && dayPeriodPart.value === 'PM' && hour !== 12) {
                hour += 12;
            }
            if (dayPeriodPart && dayPeriodPart.value === 'AM' && hour === 12) {
                hour = 0;
            }
            return hour * 60 + minute;
        };

        const tick = () => {
            if (timeEl) {
                timeEl.textContent = displayFormatter.format(new Date());
            }
            let isDaylight = Boolean(isDayFlag);
            if (sunriseMinutes !== null && sunsetMinutes !== null) {
                const nowMinutes = getCurrentMinutes();
                if (nowMinutes !== null) {
                    isDaylight = nowMinutes >= sunriseMinutes && nowMinutes < sunsetMinutes;
                }
            }
            setPhase(isDaylight);
            if (phaseEl) {
                phaseEl.textContent = isDaylight ? 'Daylight' : 'Night';
            }
            if (phaseIconEl) {
                setIcon(phaseIconEl, isDaylight ? 'fa-sun' : 'fa-moon');
            }
        };

        tick();
        setInterval(tick, 60000);
    };

    const setLocation = (value) => {
        if (!locationEl) {
            return;
        }
        locationEl.textContent = value || '';
    };

    const setFallback = (message) => {
        if (descEl) {
            descEl.textContent = message || 'Weather unavailable';
        }
        if (tempEl) {
            tempEl.textContent = '--';
        }
        setLocation('');
    };

    const applyWeatherSnapshot = (snapshot) => {
        if (!snapshot) {
            return false;
        }
        const temperature = snapshot.temperature;
        const weatherCode = Number(snapshot.weatherCode);
        const isDay = Boolean(snapshot.isDay);
        const sunriseValue = snapshot.sunrise || null;
        const sunsetValue = snapshot.sunset || null;
        const timeZone = snapshot.timeZone || 'UTC';
        const location = formatLocation(
            snapshot.city || (storeParts && storeParts.city),
            snapshot.province || (storeParts && storeParts.province),
        );

        setLocation(location);

        if (Number.isFinite(temperature) && tempEl) {
            tempEl.textContent = `${Math.round(temperature)} ${temperatureLabel}`;
        }

        let theme = isDay ? 'sun' : 'night';
        if (Number.isFinite(weatherCode)) {
            const details = describeWeather(weatherCode, isDay);
            if (descEl) {
                descEl.textContent = details.label;
            }
            setIcon(iconEl, details.icon);
            theme = details.theme;
        }
        setTheme(theme);
        setPhase(isDay);

        const snowfallCm = normalizeSnowfall(snapshot.snowfall, snapshot.snowfallUnit);
        applySnowIntensity(snowfallCm, theme === 'snow');

        if (sunriseEl) {
            sunriseEl.textContent = formatTimeValue(sunriseValue);
        }
        if (sunsetEl) {
            sunsetEl.textContent = formatTimeValue(sunsetValue);
        }

        startClock(timeZone, sunriseValue, sunsetValue, isDay);
        return true;
    };

    (async () => {
        try {
            const parts = buildStoreParts(panel.dataset || {});
            storeParts = parts;
            const storeAddress = buildStoreAddress(panel.dataset || {});
            const fallbackLocation = formatLocation(parts.city, parts.province);
            if (fallbackLocation) {
                setLocation(fallbackLocation);
            }
            if (!weatherEndpoint && !storeAddress && !parts.city && !parts.postal) {
                setFallback('Set store address');
                return;
            }

            const addressKey = normalizeAddress(
                storeAddress || parts.city || parts.postal || 'storefront',
            ).toLowerCase();
            const cachedWeather = loadCachedWeather(addressKey);
            if (cachedWeather && applyWeatherSnapshot(cachedWeather)) {
                return;
            }

            if (weatherEndpoint) {
                const response = await fetch(weatherEndpoint, {
                    headers: { Accept: 'application/json' },
                });
                let payload = null;
                try {
                    payload = await response.json();
                } catch (error) {
                    payload = null;
                }
                if (!response.ok || !payload) {
                    if (payload && payload.error === 'address_missing') {
                        setFallback('Set store address');
                        return;
                    }
                    setFallback();
                    return;
                }
                if (payload.error) {
                    if (payload.error === 'address_missing') {
                        setFallback('Set store address');
                        return;
                    }
                    setFallback();
                    return;
                }
                const normalizedPayload = {
                    ...payload,
                    city: payload.city || parts.city,
                    province: payload.province || parts.province,
                };
                storeCachedWeather(addressKey, normalizedPayload);
                applyWeatherSnapshot(normalizedPayload);
                return;
            }

            const cached = loadCachedCoords(addressKey);
            const coords = cached || await geocodeStore(parts);
            if (!cached) {
                storeCachedCoords(addressKey, coords);
            }

            const data = await fetchWeather(coords);
            const current = data.current || data.current_weather || {};
            const temperature = current.temperature_2m ?? current.temperature;
            const weatherCode = Number(current.weathercode);
            const isDay = Number(current.is_day) === 1;
            const resolvedCity = coords.city || parts.city;
            const resolvedProvince = coords.province || parts.province;

            const sunriseValue = data.daily && data.daily.sunrise ? data.daily.sunrise[0] : null;
            const sunsetValue = data.daily && data.daily.sunset ? data.daily.sunset[0] : null;
            const timeZone = data.timezone || 'UTC';
            const snowfallRaw = resolveSnowfallAmount(data);
            const snowfallUnits = resolveSnowfallUnits(data);
            const snapshot = {
                temperature,
                weatherCode,
                isDay,
                sunrise: sunriseValue,
                sunset: sunsetValue,
                timeZone,
                snowfall: snowfallRaw,
                snowfallUnit: snowfallUnits,
                city: resolvedCity,
                province: resolvedProvince,
            };
            storeCachedWeather(addressKey, snapshot);
            applyWeatherSnapshot(snapshot);
        } catch (error) {
            setFallback();
        }
    })();
})();
