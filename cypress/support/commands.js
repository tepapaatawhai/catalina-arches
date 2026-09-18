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

    // Both fields are on the same page (catalina/templates/login.htm
    // overrides Arches' default two-step username-then-password form), so
    // fill both before submitting. Pressing enter after just the username
    // submits the form early with an empty password, and a second attempt
    // after that fails again with the username field back to blank.
    cy.get('.input-group > input[name="username"].form-control').type(`admin`);
    cy.get('.input-group > input[name="password"].form-control').type(`admin{enter}`);

    // Wait for the post-login redirect so the session cookie is actually
    // set before callers issue any cy.request() calls.
    cy.url().should("include", "/index.htm");
});
