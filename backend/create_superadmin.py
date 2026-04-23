import argparse
import uuid

from sqlalchemy import select

from auth import hash_password
from db import SessionLocal
from models import User, UserRole, UserTenant, Tenant


def main():
    parser = argparse.ArgumentParser(description="Create or update a superadmin user.")
    parser.add_argument("--email", required=True, help="Superadmin email")
    parser.add_argument("--password", required=True, help="Superadmin password")
    parser.add_argument(
        "--tenant-slug",
        default="default-tenant",
        help="Tenant slug to attach the superadmin to",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.execute(select(Tenant).where(Tenant.slug == args.tenant_slug)).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                id=uuid.uuid4(),
                name="Default Tenant" if args.tenant_slug == "default-tenant" else args.tenant_slug,
                slug=args.tenant_slug,
                status="active",
            )
            db.add(tenant)
            db.flush()

        user = db.execute(select(User).where(User.email == args.email)).scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email=args.email,
                password_hash=hash_password(args.password),
                role=UserRole.superadmin,
                is_active=True,
            )
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password(args.password)
            user.role = UserRole.superadmin
            user.is_active = True

        membership = db.execute(
            select(UserTenant).where(UserTenant.user_id == user.id, UserTenant.tenant_id == tenant.id)
        ).scalar_one_or_none()
        if membership is None:
            db.add(
                UserTenant(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    tenant_id=tenant.id,
                    membership_role="owner",
                )
            )

        db.commit()
        print(f"Superadmin ready: {args.email} (tenant: {tenant.slug})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
