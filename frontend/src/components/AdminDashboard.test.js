import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  });

  it("shows WooCommerce as a source db type option", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/dashboard/settings/db-settings"]}>
        <AdminDashboard role="superadmin" tenantId="tenant-a" tenantIds={["tenant-a"]} />
      </MemoryRouter>
    );

    const select = await screen.findByLabelText("Source DB Type");
    fireEvent.mouseDown(select);

    await waitFor(() => {
      expect(screen.getByText("WooCommerce")).toBeInTheDocument();
      expect(screen.getByText("WordPress")).toBeInTheDocument();
      expect(screen.getByText("Static-only")).toBeInTheDocument();
    });
  });
});
