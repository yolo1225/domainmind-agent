import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import vuePlugin from 'eslint-plugin-vue'

const typescriptRules = {
  'no-unused-vars': 'off',
  '@typescript-eslint/no-unused-vars': [
    'error',
    { argsIgnorePattern: '^_', caughtErrors: 'none', varsIgnorePattern: '^_' },
  ],
}

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  ...vuePlugin.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tsParser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      ...typescriptRules,
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    files: ['**/*.ts'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: typescriptRules,
  },
]
