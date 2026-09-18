// ***********************************************
// This example commands.js shows you how to
// create various custom commands and overwrite
// existing commands.
//
// For more comprehensive examples of custom
// commands please read more here:
// https://on.cypress.io/custom-commands
// ***********************************************
//
//
// -- This is a parent command --
// Cypress.Commands.add("login", (email, password) => { ... })
//
//
// -- This is a child command --
// Cypress.Commands.add("drag", { prevSubject: 'element'}, (subject, options) => { ... })


Cypress.Commands.add("login", () => {
    cy.visit('/auth/?next=/index.htm');

    cy.get('.input-group > input[name="username"].form-control').type(`admin{enter}`);
    cy.get('.input-group > input[name="password"].form-control').type(`admin{enter}`);

    // Wait for the post-login redirect so the session cookie is actually
    // set before callers issue any cy.request() calls.
    cy.url().should("include", "/index.htm");
});
