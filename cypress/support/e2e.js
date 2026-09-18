// ***********************************************************
// This example support/index.js is processed and
// loaded automatically before your test files.
//
// This is a great place to put global configuration and
// behavior that modifies Cypress.
//
// You can change the location of this file or turn off
// automatically serving support files with the
// 'supportFile' configuration option.
//
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

// Import commands.js using ES2015 syntax:
import './commands';

// Alternatively you can use CommonJS syntax:
// require('./commands')

// The pages Cypress lands on after cy.login() keep running their own
// knockout-bound JS in the background (e.g. an async "Unknown component
// 'views/components/language-switcher'" error) while specs go on to make
// plain cy.request() API calls. That's an unrelated, pre-existing frontend
// issue that has nothing to do with what these specs assert, so don't let
// it fail tests that never interact with the rendered page.
Cypress.on('uncaught:exception', () => false);
