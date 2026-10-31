"use strict";

const apiEndpoints = document.querySelector("#apiEndpoints");
const apiMessage = document.querySelector("#apiMessage");
const apiVersion = document.querySelector("#apiVersion");
const apiSummary = document.querySelector("#apiSummary");
const methodOrder = ["get", "post", "put", "patch", "delete"];

function addText(parent, tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function addSchema(parent, title, schema) {
  if (!schema || Object.keys(schema).length === 0) return;
  addText(parent, "h3", "", title);
  const block = addText(parent, "pre", "schema-block", JSON.stringify(schema, null, 2));
  block.setAttribute("aria-label", `${title} schema`);
}

function buildEndpoint(path, method, operation) {
  const details = document.createElement("details");
  details.className = "endpoint";

  const summary = document.createElement("summary");
  const methodBadge = addText(summary, "span", `method method-${method}`, method.toUpperCase());
  methodBadge.setAttribute("aria-label", `${method.toUpperCase()} method`);
  addText(summary, "code", "endpoint-path", path);
  addText(summary, "span", "endpoint-summary", operation.summary || operation.operationId || "API operation");
  details.append(summary);

  const content = document.createElement("div");
  content.className = "endpoint-details";
  if (operation.description) addText(content, "p", "", operation.description);

  if (Array.isArray(operation.parameters) && operation.parameters.length) {
    addText(content, "h3", "", "Parameters");
    const list = document.createElement("ul");
    for (const parameter of operation.parameters) {
      const location = parameter.in ? ` · ${parameter.in}` : "";
      const required = parameter.required ? " · required" : "";
      addText(list, "li", "", `${parameter.name || "parameter"}${location}${required}${parameter.description ? ` — ${parameter.description}` : ""}`);
    }
    content.append(list);
  }

  const requestSchema = operation.requestBody?.content?.["application/json"]?.schema;
  addSchema(content, "Request body", requestSchema);

  const responses = operation.responses || {};
  const responseCodes = Object.keys(responses).sort();
  if (responseCodes.length) {
    addText(content, "h3", "", "Responses");
    const list = document.createElement("ul");
    for (const code of responseCodes) {
      const description = responses[code]?.description || "Response";
      addText(list, "li", "", `${code} — ${description}`);
    }
    content.append(list);
  }
  details.append(content);
  return details;
}

async function loadApiReference() {
  try {
    const response = await fetch("/openapi.json", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Schema request failed with HTTP ${response.status}`);
    const schema = await response.json();
    const paths = schema.paths || {};
    const endpoints = [];

    for (const [path, operations] of Object.entries(paths)) {
      for (const method of methodOrder) {
        if (operations[method]) endpoints.push({ path, method, operation: operations[method] });
      }
    }

    endpoints.sort((left, right) => left.path.localeCompare(right.path) || methodOrder.indexOf(left.method) - methodOrder.indexOf(right.method));
    apiVersion.textContent = `OpenAPI ${schema.openapi || ""}`.trim();
    apiSummary.textContent = `${endpoints.length} operations · ${schema.info?.title || "OpsDesk"} ${schema.info?.version || ""}`.trim();
    apiEndpoints.replaceChildren(...endpoints.map(({ path, method, operation }) => buildEndpoint(path, method, operation)));
    if (!endpoints.length) apiMessage.textContent = "The API schema loaded, but no operations were found.";
  } catch (error) {
    apiMessage.textContent = "Could not load the API schema. Check that the local OpsDesk server is running, then reload this page.";
    apiVersion.textContent = "Schema unavailable";
    apiSummary.textContent = "Endpoint definitions could not be loaded.";
    console.error("OpsDesk API reference failed to load", error);
  }
}

loadApiReference();
