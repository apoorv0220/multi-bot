import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import AdminDashboard from "./AdminDashboard";

jest.mock("../api", () => ({
  client: {
    defaults: { baseURL: "" },
    get: jest.fn(),
    patch: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

const { client } = require("../api");

describe("AdminDashboard source config", () => {
  beforeEach(() => {
    client.patch.mockClear();
    client.get.mockImplementation((url) => {
      if (url === "/api/admin/tenants") {
        return Promise.resolve({
          data: [
            {
              id: "tenant-a",
              name: "Acme",
              source_db_type: "woocommerce",
              source_mode: "mixed",
              source_table_prefix: "wp_",
              source_url_table: "wp_custom_urls",
              source_static_urls_json: "",
              source_domain_aliases: "",
              source_canonical_base_url: "",
            },
          ],
        });
      }
      return Promise.resolve({ data: [] });
    });
    client.patch.mockResolvedValue({ data: { status: "ok" } });
    client.post.mockResolvedValue({ data: {} });
    client.delete.mockResolvedValue({ data: {} });
    window.localStorage.clear();
    window.localStorage.setItem("admin_dashboard_selected_tenant_id", "tenant-a");
  });

  it("updates source mode when a menu option is selected", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/db-settings"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    const modeSelect = await screen.findByLabelText("Source Mode");
    await waitFor(() => {
      expect(modeSelect).toHaveTextContent(/Catalog \+ Static URLs/i);
    });

    fireEvent.mouseDown(modeSelect);
    const catalogOnly = await screen.findByRole("option", { name: /Catalog \+ WordPress content/i });
    fireEvent.click(catalogOnly);

    await waitFor(() => {
      expect(modeSelect).toHaveTextContent("Catalog + WordPress content");
    });
  });

  it("shows WooCommerce as a source db type option", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/db-settings"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    const select = await screen.findByLabelText("Source DB Type");
    fireEvent.mouseDown(select);
    const listbox = await screen.findByRole("listbox");

    await waitFor(() => {
      expect(within(listbox).getByRole("option", { name: "WooCommerce" })).toBeInTheDocument();
      expect(within(listbox).getByRole("option", { name: "WordPress" })).toBeInTheDocument();
      expect(within(listbox).getByRole("option", { name: "Magento" })).toBeInTheDocument();
      expect(within(listbox).getByRole("option", { name: "Static-only" })).toBeInTheDocument();
    });
  });

  it("saves coerced source_mode when db type is Magento", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/db-settings"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    const typeSelect = await screen.findByLabelText("Source DB Type");
    await userEvent.click(typeSelect);
    await userEvent.click(await screen.findByRole("option", { name: "Magento" }));
    await waitFor(() => expect(typeSelect).toHaveTextContent("Magento"));

    fireEvent.click(await screen.findByRole("button", { name: /save source settings/i }));

    await waitFor(() => {
      const call = client.patch.mock.calls.find((c) =>
        String(c[0]).includes("/source-config"),
      );
      expect(call).toBeTruthy();
      expect(call[1]).toMatchObject({ source_db_type: "magento", source_mode: "magento" });
    });
  });

  it("offers Magento source modes after switching db type to Magento", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/db-settings"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    const typeSelect = await screen.findByLabelText("Source DB Type");
    await userEvent.click(typeSelect);
    await userEvent.click(await screen.findByRole("option", { name: "Magento" }));
    await waitFor(() => expect(typeSelect).toHaveTextContent("Magento"));

    const modeSelect = await screen.findByLabelText("Source Mode");
    await userEvent.click(modeSelect);
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Magento catalog only" })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("option", { name: "Magento catalog only" }));
    await waitFor(() => {
      expect(modeSelect).toHaveTextContent("Magento catalog only");
    });
  });
});

describe("AdminDashboard retrieval profile", () => {
  beforeEach(() => {
    client.get.mockImplementation((url) => {
      if (url === "/api/admin/tenants") {
        return Promise.resolve({
          data: [{ id: "tenant-a", name: "Acme", source_db_type: "woocommerce" }],
        });
      }
      if (url === "/api/admin/tenants/tenant-a/retrieval-profile") {
        return Promise.resolve({
          data: {
            tenant_id: "tenant-a",
            retrieval_profile_version: 3,
            profile: {
              profile_version: 3,
              generated_at: "2026-05-19T12:00:00+00:00",
              stats: { product_count: 10, facet_count: 2 },
              facets: {
                color: {
                  coverage_pct: 80,
                  product_count: 8,
                  sample_values: ["chrome", "black"],
                  indexed: true,
                },
                finish: {
                  coverage_pct: 60,
                  product_count: 6,
                  sample_values: ["matt"],
                  indexed: true,
                },
              },
              category_strategy: {
                gazetteer: [{ id: "basins", labels: ["Basins"], aliases: { basin: "basins" } }],
              },
              core_fields: { price: { coverage_pct: 95, indexed: true } },
            },
            summary: { facet_ids: ["color", "finish"], product_count: 10 },
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    window.localStorage.clear();
  });

  it("renders facet rows from retrieval profile", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/retrieval-profile"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("color")).toBeInTheDocument();
      expect(screen.getByText("finish")).toBeInTheDocument();
      expect(screen.getByText("chrome")).toBeInTheDocument();
      expect(screen.getByText("Basins")).toBeInTheDocument();
    });
  });
});
