"""Processes, Process Steps, BOM lines, Operators & skills (supports Sections
16, 21, and the machine-capability / operator-skill checks of Section 23)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list

router = APIRouter(prefix="/v1", tags=["processes"])


@router.get("/processes")
def list_processes(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    processes = db.query(models.Process).all()
    out = []
    for p in processes:
        d = to_dict(p)
        d["steps"] = [
            {**to_dict(s), "bomLines": [to_dict(bl, {"materialName": bl.material.name if bl.material else None,
                                                       "unitOfMeasure": bl.material.unit_of_measure if bl.material else None})
                                          for bl in s.bom_lines]}
            for s in p.steps
        ]
        out.append(d)
    return {"items": out}


@router.post("/processes", status_code=201)
def create_process(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_PROCESSES"))):
    p = models.Process(name=body["name"], description=body.get("description"))
    db.add(p)
    db.flush()
    write_audit(db, user_id=user.id, action="CREATE_PROCESS", entity_type="PROCESS", entity_id=p.id, new_value=body)
    db.commit()
    return to_dict(p)


@router.post("/processes/{process_id}/steps", status_code=201)
def create_step(process_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_PROCESSES"))):
    process = db.get(models.Process, process_id)
    if not process:
        raise HTTPException(404, "Process not found.")
    step = models.ProcessStep(
        process_id=process_id, sequence_number=body.get("sequenceNumber", len(process.steps) + 1),
        name=body["name"], required_skill_process_id=body.get("requiredSkillProcessId"),
        standard_cycle_time=body.get("standardCycleTime", 1),
    )
    db.add(step)
    db.flush()
    for line in body.get("bomLines", []):
        db.add(models.BOMLine(process_step_id=step.id, material_id=line["materialId"], quantity_per_unit=line["quantityPerUnit"]))
    write_audit(db, user_id=user.id, action="CREATE_PROCESS_STEP", entity_type="PROCESS_STEP", entity_id=step.id, new_value=body)
    db.commit()
    return to_dict(step)


@router.post("/process-steps/{step_id}/bom-lines", status_code=201)
def add_bom_line(step_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_PROCESSES"))):
    step = db.get(models.ProcessStep, step_id)
    if not step:
        raise HTTPException(404, "Process step not found.")
    bl = models.BOMLine(process_step_id=step_id, material_id=body["materialId"], quantity_per_unit=body["quantityPerUnit"])
    db.add(bl)
    write_audit(db, user_id=user.id, action="CREATE_BOM_LINE", entity_type="BOM_LINE", entity_id=bl.id, new_value=body)
    db.commit()
    return to_dict(bl)


@router.post("/machine-capabilities", status_code=201)
def add_capability(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES", "MANAGE_PROCESSES"))):
    existing = db.query(models.MachineCapability).filter_by(machine_id=body["machineId"], process_step_id=body["processStepId"]).first()
    if existing:
        return {"ok": True}
    db.add(models.MachineCapability(machine_id=body["machineId"], process_step_id=body["processStepId"]))
    db.commit()
    return {"ok": True}


# --- Operators & skills ------------------------------------------------

@router.get("/operators")
def list_operators(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    ops = db.query(models.Operator).all()
    out = []
    for op in ops:
        d = to_dict(op, {"name": op.user.name if op.user else None, "email": op.user.email if op.user else None})
        d["skills"] = [to_dict(s, {"processName": s.process.name if s.process else None}) for s in op.skills]
        out.append(d)
    return {"items": out}


@router.post("/operators", status_code=201)
def create_operator(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS"))):
    op = models.Operator(user_id=body["userId"], employee_code=body.get("employeeCode"), shift_pattern=body.get("shiftPattern"))
    db.add(op)
    db.flush()
    write_audit(db, user_id=user.id, action="CREATE_OPERATOR", entity_type="OPERATOR", entity_id=op.id, new_value=body)
    db.commit()
    return to_dict(op)


@router.post("/operators/{operator_id}/skills", status_code=201)
def add_skill(operator_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_USERS"))):
    op = db.get(models.Operator, operator_id)
    if not op:
        raise HTTPException(404, "Operator not found.")
    skill = models.OperatorSkill(
        operator_id=operator_id, process_id=body["processId"], certified_level=body.get("certifiedLevel", "BASIC"),
        certified_date=body.get("certifiedDate"), expiry_date=body.get("expiryDate"),
    )
    db.add(skill)
    write_audit(db, user_id=user.id, action="ADD_OPERATOR_SKILL", entity_type="OPERATOR", entity_id=operator_id, new_value=body)
    db.commit()
    return {"ok": True}
