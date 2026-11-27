import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import layers from './eslint-layers.js'

export default tseslint.config(
  {
    ignores: [
      'coverage',
      'dist',
      'playwright-report',
      'test-results',
      '**/.pytest_cache/**',
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        {
          allowConstantExport: true,
          allowExportNames: [
            'buttonVariants',
            'useAuth',
            'useTheme',
          ],
        },
      ],
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/Tests/**'],
    plugins: { layers },
    rules: { 'layers/allowed-imports': 'error' },
  },
  {
    // Numbers, dates and times read in English with a 24-hour clock whatever the browser's language.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/locale.ts', 'src/Tests/**'],
    rules: {
      'no-restricted-syntax': ['error',
        { selector: "NewExpression[callee.object.name='Intl'][callee.property.name='DateTimeFormat']",
          message: 'Format dates and times with dateTimeFormat from lib/locale.' },
        { selector: "NewExpression[callee.object.name='Intl'][callee.property.name!='DateTimeFormat']:not([arguments.0.name='LOCALE'])",
          message: 'Pass LOCALE from lib/locale as the locale.' },
        { selector: "CallExpression[callee.property.name='toLocaleString']:not([arguments.0.name='LOCALE'])",
          message: 'Pass LOCALE from lib/locale as the locale.' },
        { selector: "CallExpression[callee.property.name=/^toLocale(Date|Time)String$/]",
          message: 'Format dates and times with dateTimeFormat from lib/locale.' },
      ],
    },
  },
  {
    // Application code logs through clientLogger, which redacts and gates by environment.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/logger.ts', 'src/Tests/**'],
    rules: { 'no-console': 'error' },
  },
)
