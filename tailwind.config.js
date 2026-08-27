/** @type {import('tailwindcss').Config} */

/*
 * Ant Design v5 design-token mapping.
 *
 * The admin UI keeps upstream Jinja2 templates untouched; instead of editing
 * class names per template, the Tailwind color scales are remapped to the
 * official antd palettes so existing utilities (bg-indigo-600, text-gray-500,
 * ...) resolve to antd tokens. This keeps the upstream merge surface limited
 * to this single config file.
 *
 * Mapping rules:
 *   indigo       -> antd blue      (#1677ff = colorPrimary; main interactive color)
 *   blue         -> antd geekblue  (secondary blue, keeps badge contrast vs primary)
 *   gray, slate  -> antd neutral   (works for both light and `dark:` variants)
 *   red          -> antd red       (#ff4d4f = colorError)
 *   green, emerald, teal -> antd green / cyan
 *   yellow, amber, orange -> antd gold / orange
 *   purple       -> antd purple; pink -> antd magenta; rose -> antd volcano
 *
 * Tailwind's default radius scale already matches antd
 * (rounded = 4px = borderRadiusSM, rounded-md = 6px = borderRadius,
 * rounded-lg = 8px = card radius), so no radius overrides are needed.
 */

// antd neutral (gray) palette, steps 50-950
const antdNeutral = {
    50: "#fafafa",
    100: "#f5f5f7",
    200: "#f0f0f0",
    300: "#d9d9d9",
    400: "#bfbfbf",
    500: "#8c8c8c",
    600: "#595959",
    700: "#434343",
    800: "#262626",
    900: "#141414",
    950: "#000000",
};

module.exports = {
    content: [
        "./mcpgateway/templates/**/*.html",
        "./mcpgateway/static/**/*.js",
    ],
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                gray: antdNeutral,
                slate: antdNeutral,
                indigo: {
                    50: "#f0f7ff",
                    100: "#dceaff",
                    200: "#b3d4ff",
                    300: "#85bdff",
                    400: "#2997ff",
                    500: "#0071e3",
                    600: "#0071e3",
                    700: "#0060c2",
                    800: "#004e9e",
                    900: "#003d7a",
                    950: "#002850",
                },
                blue: {
                    50: "#f0f5ff",
                    100: "#d6e4ff",
                    200: "#adc6ff",
                    300: "#85a5ff",
                    400: "#597ef7",
                    500: "#2f54eb",
                    600: "#2f54eb",
                    700: "#1d39c4",
                    800: "#10239e",
                    900: "#061178",
                    950: "#030852",
                },
                red: {
                    50: "#fff1f0",
                    100: "#ffccc7",
                    200: "#ffa39e",
                    300: "#ff7875",
                    400: "#ff4d4f",
                    500: "#ff4d4f",
                    600: "#f5222d",
                    700: "#cf1322",
                    800: "#a8071a",
                    900: "#820014",
                    950: "#5c0011",
                },
                green: {
                    50: "#f6ffed",
                    100: "#d9f7be",
                    200: "#b7eb8f",
                    300: "#95de64",
                    400: "#73d13d",
                    500: "#52c41a",
                    600: "#52c41a",
                    700: "#389e0d",
                    800: "#237804",
                    900: "#135200",
                    950: "#092b00",
                },
                emerald: {
                    50: "#f6ffed",
                    100: "#d9f7be",
                    200: "#b7eb8f",
                    300: "#95de64",
                    400: "#73d13d",
                    500: "#52c41a",
                    600: "#52c41a",
                    700: "#389e0d",
                    800: "#237804",
                    900: "#135200",
                    950: "#092b00",
                },
                teal: {
                    50: "#e6fffb",
                    100: "#b5f5ec",
                    200: "#87e8de",
                    300: "#5cdbd3",
                    400: "#36cfc9",
                    500: "#13c2c2",
                    600: "#13c2c2",
                    700: "#08979c",
                    800: "#006d75",
                    900: "#00474f",
                    950: "#002329",
                },
                cyan: {
                    50: "#e6fffb",
                    100: "#b5f5ec",
                    200: "#87e8de",
                    300: "#5cdbd3",
                    400: "#36cfc9",
                    500: "#13c2c2",
                    600: "#13c2c2",
                    700: "#08979c",
                    800: "#006d75",
                    900: "#00474f",
                    950: "#002329",
                },
                yellow: {
                    50: "#fffbe6",
                    100: "#fff1b8",
                    200: "#ffe58f",
                    300: "#ffd666",
                    400: "#ffc53d",
                    500: "#faad14",
                    600: "#faad14",
                    700: "#d48806",
                    800: "#ad6800",
                    900: "#874d00",
                    950: "#612500",
                },
                amber: {
                    50: "#fffbe6",
                    100: "#fff1b8",
                    200: "#ffe58f",
                    300: "#ffd666",
                    400: "#ffc53d",
                    500: "#faad14",
                    600: "#faad14",
                    700: "#d48806",
                    800: "#ad6800",
                    900: "#874d00",
                    950: "#612500",
                },
                orange: {
                    50: "#fff7e6",
                    100: "#ffe7ba",
                    200: "#ffd591",
                    300: "#ffc069",
                    400: "#ffa940",
                    500: "#fa8c16",
                    600: "#fa8c16",
                    700: "#d46b08",
                    800: "#ad4e00",
                    900: "#873800",
                    950: "#612500",
                },
                purple: {
                    50: "#f9f0ff",
                    100: "#efdbff",
                    200: "#d3adf7",
                    300: "#b37feb",
                    400: "#9254de",
                    500: "#722ed1",
                    600: "#722ed1",
                    700: "#531dab",
                    800: "#391085",
                    900: "#22075e",
                    950: "#120338",
                },
                pink: {
                    50: "#fff0f6",
                    100: "#ffd6e7",
                    200: "#ffadd2",
                    300: "#ff85c0",
                    400: "#f759ab",
                    500: "#eb2f96",
                    600: "#eb2f96",
                    700: "#c41d7f",
                    800: "#9e1064",
                    900: "#780650",
                    950: "#520339",
                },
                rose: {
                    50: "#fff2e8",
                    100: "#ffd8bf",
                    200: "#ffbb96",
                    300: "#ff9c6e",
                    400: "#ff7a45",
                    500: "#fa541c",
                    600: "#fa541c",
                    700: "#d4380d",
                    800: "#ad2102",
                    900: "#871400",
                    950: "#610b00",
                },
            },
            fontFamily: {
                sans: [
                    "-apple-system",
                    "BlinkMacSystemFont",
                    "'Segoe UI'",
                    "Roboto",
                    "'Helvetica Neue'",
                    "Helvetica",
                    "'PingFang SC'",
                    "'Hiragino Sans GB'",
                    "'Microsoft YaHei'",
                    "Arial",
                    "sans-serif",
                    "'Apple Color Emoji'",
                    "'Segoe UI Emoji'",
                    "'Segoe UI Symbol'",
                ],
            },
            borderRadius: {
                DEFAULT: "8px",
                md: "10px",
                lg: "10px",
            },
            boxShadow: {
                DEFAULT: "0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)",
                sm: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
                md: "0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 9px 28px 8px rgba(0, 0, 0, 0.05)",
                lg: "0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 9px 28px 8px rgba(0, 0, 0, 0.05)",
                xl: "0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 9px 28px 8px rgba(0, 0, 0, 0.05)",
                "2xl": "0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 9px 28px 8px rgba(0, 0, 0, 0.05)",
            },
            animation: {
                float: "float 6s ease-in-out infinite",
                "pulse-soft": "pulse-soft 2s ease-in-out infinite",
                "slide-up": "slide-up 0.8s ease-out",
                "fade-in": "fade-in 1s ease-out",
            },
            keyframes: {
                float: {
                    "0%, 100%": { transform: "translateY(0px)" },
                    "50%": { transform: "translateY(-20px)" },
                },
                "pulse-soft": {
                    "0%, 100%": { opacity: "1" },
                    "50%": { opacity: "0.8" },
                },
                "slide-up": {
                    "0%": { transform: "translateY(30px)", opacity: "0" },
                    "100%": { transform: "translateY(0)", opacity: "1" },
                },
                "fade-in": {
                    "0%": { opacity: "0" },
                    "100%": { opacity: "1" },
                },
            },
        },
    },
    plugins: [],
};
