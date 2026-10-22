import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

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
    // Pages are route adapters; nothing below them may import a page.
    files: ['src/features/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}', 'src/lib/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-restricted-imports': [
        'error',
        { patterns: [{ group: ['@/pages/**', '**/pages/**'], message: 'Move shared code out of pages/.' }] },
      ],
    },
  },
  {
    files: ['src/lib/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@/pages/**', '**/pages/**'], message: 'Move shared code out of pages/.' },
            { group: ['@/features/**', '**/features/**'], message: 'lib/ may only import feature types.', allowTypeImports: true },
          ],
        },
      ],
    },
  },
)
