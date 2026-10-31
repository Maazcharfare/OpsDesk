"use strict";

const $ = id => document.getElementById(id);

async function errorText(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;

    // FastAPI returns validation failures as a list. Turn those into a short
    // message a person can act on instead of showing a generic 422 error.
    if (Array.isArray(data.detail)) {
      const messages = data.detail
        .map(issue => {
          const location = Array.isArray(issue.loc)
            ? issue.loc.filter(part => !["body", "query", "path"].includes(part))
            : [];
          const field = location.join(" ").replaceAll("_", " ");
          const message = issue.msg || "Check this value";
          return field ? field + ": " + message : message;
        })
        .filter(Boolean)
        .slice(0, 3);
      if (messages.length) return messages.join(" · ");
    }

    return "Request failed (" + response.status + ")";
  } catch {
    return "Request failed (" + response.status + ")";
  }
}

let ticketLoadId = 0;
let ticketStatsLoadId = 0;

async function loadTicketStats() {
  const loadId = ++ticketStatsLoadId;

  try {
    const response = await fetch("/api/tickets/stats");
    if (!response.ok) throw Error(await errorText(response));
    const stats = await response.json();
    if (loadId !== ticketStatsLoadId) return;

    $("metricTotal").textContent = stats.total;
    $("metricOpen").textContent = stats.open;
    $("metricProgress").textContent = stats.in_progress;
    $("metricResolved").textContent = stats.resolved;
  } catch (error) {
    if (loadId === ticketStatsLoadId) {
      console.error("Unable to load ticket totals", error);
    }
  }
}

async function loadTickets() {
  const loadId = ++ticketLoadId;

  try {
    const params = new URLSearchParams();
    if ($("ticketSearch").value.trim()) params.set("search", $("ticketSearch").value.trim());
    if ($("statusFilter").value) params.set("status", $("statusFilter").value);
    if ($("priorityFilter").value) params.set("priority", $("priorityFilter").value);
    const response = await fetch("/api/tickets?" + params.toString());
    if (!response.ok) throw Error(await errorText(response));
    if (loadId !== ticketLoadId) return;

    const tickets = await response.json();
    $("ticketCount").textContent = tickets.length + (tickets.length === 1 ? " ticket" : " tickets");

    if (!tickets.length) {
      $("tickets").textContent = "No tickets yet.";
      return;
    }

    $("tickets").replaceChildren();

    for (const ticket of tickets) {
      const box = document.createElement("article");
      box.className = "item";

      const heading = document.createElement("h3");
      heading.textContent = "#" + ticket.id + " — " + ticket.title;

      const description = document.createElement("p");
      description.textContent =
        ticket.description || "No description provided.";

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent =
        "Priority: " + ticket.priority +
        " · Created: " + ticket.created_at;

      const status = document.createElement("select");
      status.className = "ticket-status";
      status.setAttribute("aria-label", "Status for ticket " + ticket.id);

      for (const value of ["Open", "In Progress", "Resolved"]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === ticket.status;
        status.append(option);
      }

      status.addEventListener("change", async () => {
        const previousStatus = ticket.status;
        status.disabled = true;

        try {
          const response = await fetch(
            "/api/tickets/" + ticket.id,
            {
              method: "PATCH",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({status: status.value})
            }
          );

          if (!response.ok) throw Error(await errorText(response));

          $("ticketMessage").textContent =
            "Ticket #" + ticket.id + " status updated.";
          await Promise.all([loadTickets(), loadTicketStats()]);
        } catch (error) {
          $("ticketMessage").textContent = error.message;
          status.value = previousStatus;
          status.disabled = false;
        }
      });

      const actions = document.createElement("div");
      actions.className = "ticket-actions";
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "secondary";
      editButton.textContent = "Edit details";
      editButton.addEventListener("click", () => {
        $("editTicketId").value = ticket.id;
        $("editTicketTitle").value = ticket.title;
        $("editTicketDescription").value = ticket.description || "";
        $("editTicketPriority").value = ticket.priority;
        $("editTicketDialog").showModal();
      });
      actions.append(editButton);
      box.append(heading, description, meta, status, actions);
      $("tickets").append(box);
    }
  } catch (error) {
    if (loadId === ticketLoadId) {
      $("tickets").textContent = "Unable to load tickets: " + error.message;
    }
  }
}

async function loadServices() {
  try {
    const response = await fetch("/api/services");
    if (!response.ok) throw Error(await errorText(response));

    const services = await response.json();
    $("serviceCount").textContent = services.length + (services.length === 1 ? " service" : " services");

    if (!services.length) {
      $("services").textContent = "No services added yet.";
      return;
    }

    $("services").replaceChildren();

    for (const service of services) {
      const box = document.createElement("article");
      box.className = "item";

      const heading = document.createElement("h3");
      heading.textContent = service.name;

      const url = document.createElement("div");
      url.className = "meta";
      url.textContent = service.url;

      const status = document.createElement("div");
      status.className =
        service.status === "UP" ? "status-up" :
        service.status === "DOWN" ? "status-down" :
        "status-unknown";
      status.textContent = "Status: " + service.status;

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent =
        "HTTP: " + (service.http_status_code ?? "—") +
        " · Response: " +
        (service.response_time_ms == null
          ? "—"
          : service.response_time_ms + " ms") +
        " · Last checked: " + (service.last_checked_at || "Never");

      box.append(heading, url, status, meta);

      if (service.error_message) {
        const error = document.createElement("div");
        error.className = "meta";
        error.textContent = "Error: " + service.error_message;
        box.append(error);
      }

      const actions = document.createElement("div");
      actions.className = "actions";

      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Check now";

      button.addEventListener("click", async () => {
        button.disabled = true;
        button.textContent = "Checking...";
        $("serviceMessage").textContent = "";

        try {
          const result = await fetch(
            "/api/services/" + service.id + "/check",
            {method: "POST"}
          );

          if (!result.ok) throw Error(await errorText(result));

          $("serviceMessage").textContent =
            "Service check completed.";
          await loadServices();
        } catch (error) {
          $("serviceMessage").textContent = error.message;
        } finally {
          button.disabled = false;
          button.textContent = "Check now";
        }
      });

      actions.append(button);
      box.append(actions);
      $("services").append(box);
    }
  } catch (error) {
    $("services").textContent =
      "Unable to load services: " + error.message;
  }
}

$("serviceForm").addEventListener("submit", async event => {
  event.preventDefault();

  const button = $("serviceForm").querySelector('button[type="submit"]');
  button.disabled = true;
  $("serviceMessage").textContent = "Adding service...";

  try {
    const response = await fetch("/api/services", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        name: $("serviceName").value.trim(),
        url: $("serviceUrl").value.trim()
      })
    });

    if (!response.ok) throw Error(await errorText(response));

    $("serviceForm").reset();
    $("serviceMessage").textContent =
      "Service added. Click Check now to test it.";
    await loadServices();
  } catch (error) {
    $("serviceMessage").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("cancelTicketEdit").addEventListener("click", () => $("editTicketDialog").close());
$("ticketEditForm").addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("saveTicketEdit");
  button.disabled = true;
  try {
    const id = $("editTicketId").value;
    const response = await fetch("/api/tickets/" + id, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        title: $("editTicketTitle").value.trim(),
        description: $("editTicketDescription").value.trim(),
        priority: $("editTicketPriority").value
      })
    });
    if (!response.ok) throw Error(await errorText(response));
    $("editTicketDialog").close();
    $("ticketMessage").textContent = "Ticket #" + id + " updated.";
    await Promise.all([loadTickets(), loadTicketStats()]);
  } catch (error) {
    $("ticketMessage").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("ticketForm").addEventListener("submit", async event => {
  event.preventDefault();

  const button = $("ticketForm").querySelector('button[type="submit"]');
  button.disabled = true;
  $("ticketMessage").textContent = "Saving ticket...";

  try {
    const response = await fetch("/api/tickets", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        title: $("title").value.trim(),
        description: $("description").value.trim(),
        priority: $("priority").value
      })
    });

    if (!response.ok) throw Error(await errorText(response));

    const ticket = await response.json();
    $("ticketForm").reset();
    $("ticketMessage").textContent =
      "Ticket #" + ticket.id + " created successfully.";
    await Promise.all([loadTickets(), loadTicketStats()]);
  } catch (error) {
    $("ticketMessage").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

let ticketFilterTimer;
$("ticketSearch").addEventListener("input", () => {
  clearTimeout(ticketFilterTimer);
  ticketFilterTimer = setTimeout(loadTickets, 180);
});
$("statusFilter").addEventListener("change", loadTickets);
$("priorityFilter").addEventListener("change", loadTickets);

loadTickets();
loadTicketStats();
loadServices();
