"""Sections 10-11 -- User Management, Role & Permission Management."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as OrmSession

from .. import models, security
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..permissions import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from ..serialize import to_dict, to_list

router = APIRouter(tags=["users"])


@router.get("/v1/users")
def list_users(db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS", "VIEW_MACHINES"))):
    users = db.query(models.User).all()
    return {"items": [
        {**to_dict(u, {"roles": u.role_names(), "department": u.department.name if u.department else None}), "passwordHash": None}
        for u in users
    ]}


@router.post("/v1/users", status_code=201)
def create_user(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS"))):
    for field in ("name", "email", "username", "password"):
        if not body.get(field):
            raise HTTPException(400, f"Missing required field: {field}")
    if db.query(models.User).filter(models.User.username == body["username"]).first():
        raise HTTPException(400, "Username must be unique.")
    if db.query(models.User).filter(models.User.email == body["email"]).first():
        raise HTTPException(400, "Email must be unique.")
    problems = security.validate_password_policy(body["password"])
    if problems:
        raise HTTPException(400, "; ".join(problems))

    role_ids = body.get("roleIds", [])
    roles = []
    for rid in role_ids:
        role = db.get(models.Role, rid)
        if not role:
            raise HTTPException(400, f"Assigned role {rid} does not exist.")
        roles.append(role)

    new_user = models.User(
        name=body["name"], email=body["email"], phone=body.get("phone"),
        username=body["username"], password_hash=security.hash_password(body["password"]),
        department_id=body.get("departmentId"), status=body.get("status", "ACTIVE"),
    )
    db.add(new_user)
    db.flush()
    for role in roles:
        db.add(models.UserRole(user_id=new_user.id, role_id=role.id))

    write_audit(db, user_id=user.id, action="CREATE_USER", entity_type="USER", entity_id=new_user.id,
                new_value={"username": new_user.username, "roles": [r.name for r in roles]})
    db.commit()
    return to_dict(new_user, {"roles": new_user.role_names()})


@router.patch("/v1/users/{user_id}")
def update_user(user_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS"))):
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    old = {"status": target.status, "roles": target.role_names()}

    for field in ("name", "email", "phone", "status", "departmentId"):
        key = "department_id" if field == "departmentId" else field
        if field in body:
            setattr(target, key, body[field])

    unlocking = old["status"] == "LOCKED" and body.get("status") == "ACTIVE"
    if unlocking:
        target.lockout_until = None
        target.failed_login_count = 0

    if "roleIds" in body:
        db.query(models.UserRole).filter(models.UserRole.user_id == target.id).delete()
        for rid in body["roleIds"]:
            role = db.get(models.Role, rid)
            if not role:
                raise HTTPException(400, f"Role {rid} does not exist.")
            db.add(models.UserRole(user_id=target.id, role_id=rid))

    if "password" in body and body["password"]:
        problems = security.validate_password_policy(body["password"])
        if problems:
            raise HTTPException(400, "; ".join(problems))
        target.password_hash = security.hash_password(body["password"])

    target.updated_at = dt.datetime.utcnow()
    write_audit(db, user_id=user.id, action="UPDATE_USER" if not unlocking else "UNLOCK_USER",
                entity_type="USER", entity_id=target.id, old_value=old,
                new_value={"status": target.status, "roles": target.role_names()},
                reason=body.get("reason"))
    db.commit()
    return to_dict(target, {"roles": target.role_names()})


@router.post("/v1/users/{user_id}/mfa/setup")
def setup_mfa(user_id: str, db: OrmSession = Depends(get_db), current=Depends(get_current_user)):
    if current.id != user_id and "MANAGE_USERS" not in _perms(current):
        raise HTTPException(403, "Cannot configure MFA for another user.")
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    secret = security.new_mfa_secret()
    target.mfa_secret = secret
    db.commit()
    return {"secret": secret, "provisioningUri": security.mfa_provisioning_uri(secret, target.email)}


@router.post("/v1/users/{user_id}/mfa/confirm")
def confirm_mfa(user_id: str, body: dict, db: OrmSession = Depends(get_db), current=Depends(get_current_user)):
    if current.id != user_id and "MANAGE_USERS" not in _perms(current):
        raise HTTPException(403, "Cannot configure MFA for another user.")
    target = db.get(models.User, user_id)
    if not target or not security.verify_totp(target.mfa_secret, body.get("code", "")):
        raise HTTPException(400, "Invalid MFA code.")
    target.mfa_enabled = True
    write_audit(db, user_id=current.id, action="MFA_ENABLED", entity_type="USER", entity_id=target.id)
    db.commit()
    return {"ok": True}


def _perms(u: models.User):
    s = set()
    for r in u.role_names():
        s.update(ROLE_PERMISSIONS.get(r, []))
    return s


# --- Roles & permissions (Section 11) --------------------------------------

@router.get("/v1/roles")
def list_roles(db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_ROLES", "VIEW_MACHINES"))):
    roles = db.query(models.Role).all()
    return {"items": [
        {**to_dict(r), "permissions": [rp.permission.code for rp in r.permissions]}
        for r in roles
    ]}


@router.get("/v1/permissions")
def list_permissions(user=Depends(require_permission("MANAGE_ROLES", "VIEW_MACHINES"))):
    return {"items": [{"code": c, "description": d} for c, d in PERMISSIONS.items()]}


@router.patch("/v1/roles/{role_id}/permissions")
def set_role_permissions(role_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_ROLES"))):
    role = db.get(models.Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found.")
    codes = body.get("permissionCodes", [])
    old_codes = [rp.permission.code for rp in role.permissions]
    db.query(models.RolePermission).filter(models.RolePermission.role_id == role_id).delete()
    for code in codes:
        perm = db.query(models.Permission).filter(models.Permission.code == code).first()
        if not perm:
            raise HTTPException(400, f"Unknown permission code: {code}")
        db.add(models.RolePermission(role_id=role_id, permission_id=perm.id))
    write_audit(db, user_id=user.id, action="UPDATE_ROLE_PERMISSIONS", entity_type="ROLE", entity_id=role_id,
                old_value=old_codes, new_value=codes, reason=body.get("reason"))
    db.commit()
    return {"ok": True, "permissions": codes}


@router.get("/v1/departments")
def list_departments(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.Department).all())}


@router.post("/v1/departments", status_code=201)
def create_department(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS"))):
    dep = models.Department(name=body["name"])
    db.add(dep)
    db.commit()
    return to_dict(dep)
