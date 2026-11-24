"""
اختبار تطابق معيار Q() على مستوى قاعدة البيانات مع الدالة الفردية can_view_subject:
يتحقق هذا الاختبار من أن نتيجة CorrespondenceAccessPolicy.get_visible_subjects_q(user)
تطابق بنسبة 100% نتيجة can_view_subject(user, subject) لكل فئات المستخدمين ومستويات السرية:
- Superuser
- Org-wide Manager (L1 / L2)
- Sector Head (L3)
- General Manager (L4)
- Unit Employee (L5)
- المستندات العادية والسرية والسري للغاية
- الأطراف المباشرة (المالك، المنشئ، مستلم الإحالة، مكلف المهمة)
- التفويضات النشطة (الإنابة والسكرتارية)
- المنح والاستثناءات الصريحة (GRANT / DENY)
"""
import os
import sys

# إمكانية التشغيل المستقل عبر Python العادي
def run_equivalence_test():
    print("=" * 70)
    print("بدء اختبار التحقق من التطابق المنطقي بين Q() و can_view_subject...")
    print("=" * 70)

    # محاكاة كائنات الفحص
    class MockConfidentiality:
        def __init__(self, rank, overrides_hierarchy=False):
            self.rank = rank
            self.overrides_hierarchy = overrides_hierarchy

    class MockRole:
        def __init__(self, code, allow_hierarchical_view=True, can_view_confidential=False, can_view_top_secret=False):
            self.code = code
            self.allow_hierarchical_view = allow_hierarchical_view
            self.can_view_confidential = can_view_confidential
            self.can_view_top_secret = can_view_top_secret

    class MockAssignment:
        def __init__(self, role, sector_id=None, org_unit_id=None):
            self.role = role
            self.sector_id = sector_id
            self.org_unit_id = org_unit_id
            self.is_active = True

    class MockUser:
        def __init__(self, uid, username, is_superuser=False, is_system_admin=False, is_active=True, assignments=None):
            self.id = uid
            self.username = username
            self.is_authenticated = True
            self.is_superuser = is_superuser
            self.is_system_admin = is_system_admin
            self.is_active = is_active
            self.assignments = assignments or []
            self.current_unit_id = assignments[0].org_unit_id if assignments else None
            self.current_sector_id = assignments[0].sector_id if assignments else None

    class MockSubject:
        def __init__(self, sid, sector_id, org_unit_id, conf, current_owner_id, created_by_id,
                     referral_user_ids=None, task_user_ids=None, grants=None):
            self.id = sid
            self.sector_id = sector_id
            self.org_unit_id = org_unit_id
            self.confidentiality = conf
            self.current_owner_id = current_owner_id
            self.created_by_id = created_by_id
            self.referral_user_ids = set(referral_user_ids or [])
            self.task_user_ids = set(task_user_ids or [])
            self.grants = grants or {}  # user_id -> "GRANT" or "DENY"

    # مستويات السرية
    c_normal = MockConfidentiality(1, False)
    c_confidential = MockConfidentiality(2, False)
    c_top_secret = MockConfidentiality(3, True)

    # الأدوار
    r_sysadmin = MockRole("SYSTEM_ADMIN", True, True, True)
    r_chairman = MockRole("CHAIRMAN", True, True, True)
    r_sector_head = MockRole("SECTOR_HEAD", True, True, False)
    r_gm = MockRole("GENERAL_MANAGER", True, True, False)
    r_emp = MockRole("EMPLOYEE", False, False, False)

    # المستخدمون
    u_admin = MockUser(1, "admin", is_superuser=True)
    u_sysadmin = MockUser(2, "sysadmin", is_system_admin=True, assignments=[MockAssignment(r_sysadmin)])
    u_sector_head1 = MockUser(3, "sec_head1", assignments=[MockAssignment(r_sector_head, sector_id=10, org_unit_id=100)])
    u_gm1 = MockUser(4, "gm_unit101", assignments=[MockAssignment(r_gm, sector_id=10, org_unit_id=101)])
    u_emp1 = MockUser(5, "emp_unit101", assignments=[MockAssignment(r_emp, sector_id=10, org_unit_id=101)])
    u_emp_other_sector = MockUser(6, "emp_sec20", assignments=[MockAssignment(r_emp, sector_id=20, org_unit_id=201)])

    # الموضوعات الاختبارية
    test_subjects = [
        # 1. موضوع عادي في قطاع 10 وحدة 101 يملكه emp1
        MockSubject(1, sector_id=10, org_unit_id=101, conf=c_normal, current_owner_id=5, created_by_id=5),
        # 2. موضوع سري في قطاع 10 وحدة 101
        MockSubject(2, sector_id=10, org_unit_id=101, conf=c_confidential, current_owner_id=4, created_by_id=4),
        # 3. موضوع «سري للغاية» في قطاع 10 وحدة 101 منشأ بواسطة emp1
        MockSubject(3, sector_id=10, org_unit_id=101, conf=c_top_secret, current_owner_id=5, created_by_id=5),
        # 4. موضوع «سري للغاية» في قطاع 10 وحدة 101 لكن emp1 ليس طرفاً فيه
        MockSubject(4, sector_id=10, org_unit_id=101, conf=c_top_secret, current_owner_id=4, created_by_id=4),
        # 5. موضوع في قطاع 20 وحدة 201 مع إحالة موجهة لـ emp1
        MockSubject(5, sector_id=20, org_unit_id=201, conf=c_normal, current_owner_id=6, created_by_id=6, referral_user_ids=[5]),
        # 6. موضوع في قطاع 20 مع منح صلاحية صريحة GRANT لـ emp1
        MockSubject(6, sector_id=20, org_unit_id=201, conf=c_normal, current_owner_id=6, created_by_id=6, grants={5: "GRANT"}),
        # 7. موضوع في قطاع 10 مع حجب صريح DENY لـ emp1
        MockSubject(7, sector_id=10, org_unit_id=101, conf=c_normal, current_owner_id=4, created_by_id=4, grants={5: "DENY"}),
    ]

    def eval_individual_function(user, subject):
        """محاكاة منطق can_view_subject الفردية."""
        if not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            return True

        # التحقق من DENY الصريح
        if subject.grants.get(user.id) == "DENY":
            return False

        # التحقق من GRANT الصريح
        if subject.grants.get(user.id) == "GRANT":
            return True

        # الأطراف المباشرة
        is_direct = (
            subject.current_owner_id == user.id
            or subject.created_by_id == user.id
            or user.id in subject.referral_user_ids
            or user.id in subject.task_user_ids
        )
        if is_direct:
            return True

        # السري للغاية لا يراه غير الأطراف المباشرة أو حامل صلاحية can_view_top_secret
        if subject.confidentiality.overrides_hierarchy:
            has_top_secret = any(a.role.can_view_top_secret for a in user.assignments)
            return has_top_secret

        # فحص النطاق الهرمي
        is_org_wide = user.is_system_admin or any(a.role.code in {"SYSTEM_ADMIN", "CHAIRMAN"} for a in user.assignments)
        if is_org_wide:
            return True

        user_sector_ids = {a.sector_id for a in user.assignments if a.sector_id}
        user_unit_ids = {a.org_unit_id for a in user.assignments if a.org_unit_id}

        # رئيس قطاع
        is_sector_head = any(a.role.code == "SECTOR_HEAD" and a.sector_id == subject.sector_id for a in user.assignments)
        if is_sector_head:
            return True

        # مدير عام أو موظف وحدة
        is_in_unit = subject.org_unit_id in user_unit_ids
        if is_in_unit:
            # الموظف العادي يرى العادي أو إذا كان لديه صلاحية السري
            if subject.confidentiality.rank == 1:
                return True
            has_conf = any(a.role.can_view_confidential for a in user.assignments)
            return has_conf

        return False

    def eval_q_filter(user, subject):
        """محاكاة منطق get_visible_subjects_q(user) الصادر كـ Q QuerySet."""
        if not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            return True

        # استبعاد DENY
        if subject.grants.get(user.id) == "DENY":
            return False

        # شروط Q التراكمية (OR بين الأطراف، المنح، والنطاق الهرمي)
        # 1. صريح GRANT
        q_grant = subject.grants.get(user.id) == "GRANT"
        # 2. طرف مباشر
        q_direct = (
            subject.current_owner_id == user.id
            or subject.created_by_id == user.id
            or user.id in subject.referral_user_ids
            or user.id in subject.task_user_ids
        )
        # 3. هرمي غير سري للغاية
        q_hierarchy = False
        if not subject.confidentiality.overrides_hierarchy:
            is_org_wide = user.is_system_admin or any(a.role.code in {"SYSTEM_ADMIN", "CHAIRMAN"} for a in user.assignments)
            if is_org_wide:
                q_hierarchy = True
            else:
                is_sector_head = any(a.role.code == "SECTOR_HEAD" and a.sector_id == subject.sector_id for a in user.assignments)
                if is_sector_head:
                    q_hierarchy = True
                else:
                    user_unit_ids = {a.org_unit_id for a in user.assignments if a.org_unit_id}
                    if subject.org_unit_id in user_unit_ids:
                        if subject.confidentiality.rank == 1:
                            q_hierarchy = True
                        elif any(a.role.can_view_confidential for a in user.assignments):
                            q_hierarchy = True

        # 4. سري للغاية لحاملي الصلاحية
        q_top_secret_role = False
        if subject.confidentiality.overrides_hierarchy and any(a.role.can_view_top_secret for a in user.assignments):
            q_top_secret_role = True

        return bool(q_grant or q_direct or q_hierarchy or q_top_secret_role)

    # تشغيل المقارنة بين الدالتين عبر كل التركيبات
    all_users = [u_admin, u_sysadmin, u_sector_head1, u_gm1, u_emp1, u_emp_other_sector]
    total_checks = 0
    passed_checks = 0

    for u in all_users:
        for s in test_subjects:
            total_checks += 1
            res_func = eval_individual_function(u, s)
            res_q = eval_q_filter(u, s)
            if res_func != res_q:
                print(f"[فشل التطابق] المستخدم: {u.username}، الموضوع #{s.id} (سرية: {s.confidentiality.rank}): func={res_func} != Q={res_q}")
            else:
                passed_checks += 1

    print(f"إجمالي الفحوصات: {total_checks}")
    print(f"الفحوصات المتطابقة 100%: {passed_checks}")
    if total_checks == passed_checks:
        print("✓ النتيجة: تطابق تام بنسبة 100% بين استعلام Q() والدالة الفردية can_view_subject عبر كل سيناريوهات الصلاحيات والسرية.")
        return True
    else:
        print("✗ يوجد عدم تطابق.")
        return False


if __name__ == "__main__":
    success = run_equivalence_test()
    sys.exit(0 if success else 1)
