import globals from 'globals'
import vue from 'eslint-plugin-vue'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'vite.config.d.ts',
      'vite.config.js',
      'playwright.config.d.ts',
      'playwright.config.js',
      '*.tsbuildinfo',
    ],
  },
  ...vue.configs['flat/essential'],
  {
    files: ['**/*.ts'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parser: tsParser,
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-unused-vars': 'off',
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: {
        parser: tsParser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      'vue/multi-word-component-names': 'off',
      'vue/no-mutating-props': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-unused-vars': 'off',
    },
  },
]
