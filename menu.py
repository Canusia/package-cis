"""
JSON Menu template - better off with a role/menu factory class
"""
from django.urls import reverse


FACULTY_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'faculty:dashboard'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-users',
        'name': 'teachers',
        "image": "icn-adjunct-teacher.svg",
        'label': 'View All Teachers',
        'url': 'faculty:teachers'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-route',
        'label': 'Class Observations',
        'name': 'class_visits',
        'url': 'faculty_class_visit:visits'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'name': 'classes',
        'label': 'Syllabi Review',
        'url': 'faculty:classes'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'label': 'Teacher Applications',
        'name': 'applications',
        'url': 'faculty:applications'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-clipboard-list',
        'name': 'section_requests',
        'label': 'Section Requests',
        'url': 'future_sections_faculty:section_request_list'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file-alt',
        'name': 'syllabi_templates',
        "image": "icn-course-syllabi.svg",
        'label': 'Course Resources',
        'url': 'faculty:syllabi_templates'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-folder',
        'name': 'docrepo',
        'label': 'Documents Library',
        'url': 'faculty_docrepo:docs'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-box',
    #     'label': 'Events',
    #     'name': 'events',
    #     'url': 'pd_event_faculty:events'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-list',
    #     'label': 'Site Visits',
    #     'name': 'site_visits',
    #     'url': 'faculty:site_visits'
    # },
    #{
    #    'type': 'nav-item',
    #    'icon': 'fas fa-fw fa-box',
    #    'name': 'events',
    #    'label': 'Events',
    #    'url': ''
    #},
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-sign-out-alt',
        'name': 'logout',
        'label': 'Logout',
        'url': 'logout'
    },
]

INSTRUCTOR_APP_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'instructor_app:dashboard'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'label': 'Manage Application',
        'name': 'manage_app'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'name': 'profile',
        'label': 'My Profile',
        'url': 'instructor_app:profile'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-key',
        'name': 'manage_password',
        'label': 'Manage Password',
        'url': 'instructor_app:manage_password'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-sign-out-alt',
        'name': 'logout',
        'label': 'Logout',
        'url': 'logout'
    },
]

cis_menu = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'dashboard',
        'label': 'Dashboard',
        'url': 'cis:dashboard'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'label': 'Announcements',
        'name': 'announcements',
        'sub_menu': [
            {
                'label': 'All',
                'name': 'all',
                'url': 'announcements:all'
            },
            {
                'label': 'Bulk Messages',
                'name': 'bulk_messages',
                'url': 'announcements:bulk_messages'
            },
            {
                'label': 'Bulk Message Logs',
                'name': 'bulk_message_logs',
                'url': 'announcements:bulk_message_logs'
            },
        ]
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-bullhorn',
    #     'label': 'Announcements',
    #     'name': 'announcements',
    #     'url': 'announcements:all'
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'label': 'Degree Pathways',
        'name': 'degree_pathways',
        'sub_menu': [
            {
                'label': 'All Pathways',
                'name': 'degree_pathways',
                'url': 'academic_plan_ce:degree_pathways'
            },
            {
                'label': 'Areas of Interest',
                'name': 'areas_of_interest',
                'url': 'academic_plan_ce:areas_of_interest'
            },
            {
                'label': 'Academic Plans',
                'name': 'academic_plans',
                'url': 'academic_plan_ce:academic_plans'
            },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'label': 'Students',
        'name': 'students',
        'sub_menu': [
            {
                'label': 'All Students',
                'name': 'students',
                'url': 'cis:students'
            },
            {
                'label': 'Recommendations',
                'name': 'recommendations',
                'url': 'cis:recommendations'
            },
            {
                'label': 'Certs. Of Residence',
                'name': 'support_docs',
                'url': 'cis:support_docs'
            },
            {
                'label': 'Registrations',
                'name': 'registrations',
                'url': 'cis:registrations'
            },
            {
                'label': 'Failed SIS Mirror',
                'name': 'registrations_failed_mirror',
                'url': 'cis:registrations_failed_mirror'
            },
            {
                'label': 'Pending SIS Mirror',
                'name': 'registrations_pending_mirror',
                'url': 'cis:registrations_pending_mirror'
            },
            {
                'label': 'Transactions',
                'name': 'transactions',
                'url': 'student_transactions:index'
            },
            {
                'label': 'Drop/WD Requests',
                'name': 'drop_wd_requests',
                'url': 'ce_drop_wd:requests'
            },
            {
                'label': 'Notes',
                'name': 'notes',
                'url': 'cis:students_notes'
            },
            {
                'label': 'SIS Messages',
                'name': 'sis_messages',
                'url': 'cis:sis_messages'
            },
            {
                'label': 'SIS Logs',
                'name': 'sis_logs',
                'url': 'cis:sis_logs'
            },
        ]
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-ticket-alt',
    #     'label': 'Support Requests',
    #     'name': 'support_reqs',
    #     'sub_menu': [
    #         {
    #             'label': 'All Requests',
    #             'name': 'requests',
    #             'url': 'support_ticket:requests'
    #         },
    #         {
    #             'label': 'Manage Types',
    #             'name': 'types',
    #             'url': 'support_ticket:types'
    #         },
    #         {
    #             'label': 'Manage Settings',
    #             'name': 'settings',
    #             'url': 'support_ticket:settings'
    #         },
    #     ]
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-vihara',
        'label': 'Campus',
        'name': 'campus',
        'sub_menu': [
            {
                'label': 'All Campus',
                'name': 'campuses',
                'url': 'cis:campuses'
            },
            # {
            #     'label': 'Locations',
            #     'name': 'locations',
            #     'url': 'cis:locations'
            # },
            # {
            #     'label': 'UMA Centers',
            #     'name': 'tech_center',
            #     'url': 'cis:tech_centers'
            # },
            # {
            #     'label': 'UMA Center Staff',
            #     'name': 'tech_center_staff',
            #     'url': 'cis:tech_center_staffs'
            # }, 
            # {
            #     'label': 'Categories',
            #     'name': 'categories',
            #     'url': 'cis:categories'
            # },
            # {
            #     'label': 'Colleges',
            #     'name': 'colleges',
            #     'url': 'cis:colleges'
            # },
            # {
            #     'label': 'Departments',
            #     'name': 'departments',
            #     'url': 'cis:departments'
            # },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-vihara',
        'label': 'High Schools',
        'name': 'highschools',
        'sub_menu': [
            {
                'label': 'All High Schools',
                'name': 'all_highschools',
                'url': 'cis:highschools'
            },
            {
                'label': 'School Admin.',
                'name': 'school_administrators',
                'url': 'cis:hs_admins'
            },
            {
                'label': 'Access Requests',
                'name': 'access_requests',
                'url': 'cis:hs_admin_access_requests'
            },
            {
                'label': 'Admin. Roles',
                'name': 'school_roles',
                'url': 'cis:hs_roles'
            },
            
            # {
                # 'label': 'Instructor Applicants',
                # 'name': 'all_applicants',
                # 'url': ''
            # },
            # {
            #     'label': '',
            #     'type': 'separator'
            # },
            {
                'label': 'All Districts',
                'name': 'all_districts',
                'url': 'cis:districts'
            },
            # {
            #     'label': 'District Admins.',
            #     'name': 'district_admins',
            #     'url': 'cis:district_admins'
            # },
            # {
            #     'label': 'District Roles',
            #     'name': 'district_roles',
            #     'url': 'cis:district_roles'
            # },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-align-left',
        'label': 'Classes',
        'name': 'classes',
        'sub_menu': [
            {
                'label': 'Sections',
                'name': 'sections',
                'url': 'cis:sections'
            },
            {
                'label': 'Course Projections',
                'name': 'future_sections',
                'url': 'cis:future_sections'
            },
            {
                'label': 'Review Section Requests',
                'name': 'section_requests',
                'url': 'future_sections_ce:section_request_list'
            },
            {
                'label': 'Class Visits/Reports',
                'name': 'class_visits',
                'url': 'class_visit:visits'
            },
            {
                'type': 'nav-item',
                'icon': 'fas fa-fw fa-box',
                'name': 'course_search',
                'label': 'Course Search',
                'url': 'cis:course_search'
            },
            # {
            #     'label': 'Section No.',
            #     'name': 'section_numbers',
            #     'url': 'cis:section_numbers'
            # },
            {
                'label': '',
                'type': 'separator'
            },
            {
                'label': 'Courses',
                'name': 'courses',
                'url': 'cis:courses'
            },
            {
                'label': 'Subjects',
                'name': 'cohorts',
                'url': 'cis:cohorts'
            },
            {
                'label': '',
                'type': 'separator'
            },
            {
                'label': 'Academic Years',
                'name': 'academic_years',
                'url': 'cis:academic_years'
            },
            {
                'label': 'Terms',
                'name': 'terms',
                'url': 'cis:terms'
            },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user-shield',
        'label': 'Instructors',
        'name': 'instructors',
        'sub_menu': [
            # {
            #     'label': 'College Faculty',
            #     'name': 'college_instructors',
            #     'url': 'cis:college_instructors'
            # },
            {
                'label': 'All Instructors',
                'name': 'instructors',
                'url': 'cis:instructors'
            },
            {
                'label': 'Instructor Applicants',
                'name': 'all_applicants',
                'url': 'cis:teacher_applications'
            },
            {
                'label': 'Teacher Course Certificates',
                'name': 'credentials',
                'url': 'cis:credentials'
            },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-users',
        'label': 'Faculty',
        'name': 'fac_coords',
        'url': 'cis:faculty_coordinators'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'label': 'Events',
        'name': 'events',
        'sub_menu': [
            {
                'label': 'Events',
                'name': 'event_list',
                'url': 'pd_event:events'
            },
            {
                'label': 'Event Types',
                'name': 'event_types',
                'url': 'pd_event:event_types'
            },
            # {
            #     'label': 'Speakers',
            #     'name': 'speakers',
            #     'url': 'cis:speakers'
            # },
            # {
            #     'label': 'Venues',
            #     'name': 'venue',
            #     'url': 'cis:venues'
            # },
        ]
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file-alt',
        'name': 'reports',
        'label': 'Reports',
        'url': 'report:reports'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-cog',
        'name': 'settings',
        'label': 'Settings',
        'url': 'setting:records'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-folder',
        'label': 'Documents',
        'name': 'docrepo',
        'url': 'docrepo:all'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-users',
        'label': 'Staff',
        'name': 'users',
        'sub_menu': [
            {
                'label': 'All Staff',
                'name': 'users',
                'url': 'cis:users'
            },
            {
                'label': 'Scheduled Tasks',
                'name': 'cron',
                'url': 'cis:cronlog'
            },
        ]
    },
]


STUDENT_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'student:dashboard'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-clipboard-check',
        'name': 'ferpa',
        'label': 'FERPA Consent',
        'url': 'student:ferpa'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-home',
    #     'name': 'supporting_docs',
    #     'label': 'Cert. of Residence',
    #     'url': 'student:support_docs'
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-book',
        'name': 'classes',
        'label': 'Apply for Classes',
        'url': 'student:classes'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-book',
        'name': 'degree_plan',
        "image": "icn-academic-plan.svg",
        'label': 'My Academic Plan(s)',
        'url': 'academic_plan_student:step_1'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file',
        'name': 'drop_wd_requests',
        'label': 'Drop/WD Requests',
        'url': 'student_drop_wd:requests'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-file-signature',
    #     'name': 'classes',
    #     'label': 'Student Agreement',
    #     'url': 'student:classes'
    # },
    {
        "type": "nav-item",
        "icon": "fas fa-fw fa-file-contract",
        "name": "parent_consent",
        "label": "Parental Consent",
        "url": "student:parent_consent"
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'name': 'profile',
        'label': 'My Profile',
        'url': 'student:profile'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-folder',
    #     'name': 'docrepo',
    #     'label': 'Documents',
    #     'url': 'student_docrepo:docs'
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-key',
        'name': 'manage_password',
        'label': 'Manage Password',
        'url': 'student:manage_password'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-sign-out-alt',
        'name': 'logout',
        'label': 'Logout',
        'url': 'logout'
    },
]

TECH_CENTER_STAFF_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'tech_center_staff:dashboard'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-user',
        'name': 'students',
        'label': 'Students',
        'url': 'tech_center_staff:students'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-users',
        'name': 'registrations',
        'label': 'Registrations',
        'url': 'tech_center_staff:registrations'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'name': 'course_search',
        'label': 'Course Search',
        'url': 'tech_center_staff:course_search'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-sign-out-alt',
        'name': 'logout',
        'label': 'Logout',
        'url': 'logout'
    },
]


HS_ADMIN_MENU = [
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-tachometer-alt',
    #     'name': 'home',
    #     'label': 'Home',
    #     'url': 'highschool_admin:dashboard'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-user',
    #     'label': 'Students',
    #     'name': 'students',
    #     'url': 'highschool_admin:students'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-edit',
    #     'label': 'Student Notes',
    #     'name': 'notes',
    #     'url': 'highschool_admin:student_notes'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-file',
    #     'name': 'transcripts',
    #     'label': 'Transcripts',
    #     'url': 'highschool_admin:transcripts'
    # },
    # # {
    # #     'type': 'nav-item',
    # #     'icon': 'fas fa-fw fa-box',
    # #     'name': 'course_search',
    # #     'label': 'Course Search',
    # #     'url': 'highschool_admin:course_search'
    # # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-file',
    #     'name': 'section_requests',
    #     'label': 'Course Projections',
    #     'url': 'highschool_admin:section_requests'
    # },

    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-file',
    #     'name': 'drop_wd_requests',
    #     'label': 'Drop/WD Requests',
    #     'url': 'highschool_admin_drop_wd:requests'
    # },
    # # {
    # #     'type': 'nav-item',
    # #     'icon': 'fas fa-fw fa-question-circle',
    # #     'name': 'support',
    # #     'label': 'Support Requests',
    # #     'url': 'hs_admin_support_ticket:requests'
    # # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-file-alt',
    #     'name': 'reports',
    #     'label': 'Reports',
    #     'url': 'highschool_admin_report:reports'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-users',
    #     'name': 'administrators',
    #     'label': 'School Personnel',
    #     'url': 'highschool_admin:personnel'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-key',
    #     'name': 'manage_password',
    #     'label': 'Manage Password',
    #     'url': 'highschool_admin:manage_password'
    # },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-sign-out-alt',
    #     'name': 'logout',
    #     'label': 'Logout',
    #     'url': 'logout'
    # },
]

INSTRUCTOR_MENU = [
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-tachometer-alt',
        'name': 'home',
        'label': 'Home',
        'url': 'instructor:dashboard'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-stream',
    #     'name': 'course_apps',
    #     'label': 'My Course Applications',
    #     'url': 'instructor:course_apps'
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-box',
        'name': 'classes',
        'sub_menu': [
            {
                'label': 'All My Classes',
                'name': 'classes',
                'url': 'instructor:classes'
            },
            {
                'label': 'Class Section',
                'name': 'class'
            },
        ],
        'label': 'Class Section(s)',
        'url': 'instructor:classes'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-users',
        'label': 'My Students',
        'name': 'students',
        'url': 'instructor:students'
    },
    # {
    #     'type': 'nav-item',
    #     'icon': 'fas fa-fw fa-list-ul',
    #     'name': 'grades',
    #     'label': 'Class Grades',
    #     'url': 'instructor:grades'
    # },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file',
        'name': 'drop_wd_requests',
        'label': 'Drop/WD Requests',
        'url': 'instructor_drop_wd:requests'
    },

    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-file',
        'name': 'uploads',
        'label': 'My Files',
        'url': 'instructor:uploads'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-folder',
        'name': 'docrepo',
        'label': 'Shared Docs.',
        'url': 'instructor_docrepo:docs'
    },
    {
        'type': 'nav-item',
        'icon': 'fas fa-fw fa-sign-out-alt',
        'name': 'logout',
        'label': 'Logout',
        'url': 'logout'
    },
]

def draw_menu(menu, active_menu, active_submenu='', role_name='ce'):
    result = ''
    import json
    from cis.settings.menu import menu as menu_settings
    
    conf = menu_settings.from_db()
    try:
        menu = json.loads(conf.get(f'{role_name}_menu'))
    except:
        return result

    for item in menu:
        if not item.get('display', True):
            continue

        if item['type'] == 'nav-item':
            result += "<li class='nav-item "
            if active_menu == item['name']:
                result += 'active'
            result += "' id='id_nav_item_" + item['name'] + "'>\n"

            try:
                result += "<a class='nav-link"
                if item.get('sub_menu', None):
                    if active_menu == item['name']:
                        result += "' aria-expanded='true' "
                    else:
                        result += " collapsed' aria-expanded='false' "
                    result += f" data-toggle='collapse' data-target='#collapse{item['name']}'  aria-control='collapse" + item['name'] + "' "
                else:
                    result += "'"
                result += " href='"
                if item.get('url', ''):
                    result += reverse(item['url'])
                result += "'>\n"

                result += "<i class='" + item['icon'] + "'></i>"
                result += f"<span>{item['label']}</span>"
                result += "</a>"
            except Exception as e:
                print(e)

            if item.get('sub_menu', None):
                show_sub_menu = ''
                if active_menu == item['name']:
                    show_sub_menu = "show"

                result += f"<div id='collapse{item['name']}' class='collapse "
                result += f"{show_sub_menu}' data-parent='#accordionSidebar'>"
                result += "<div class='bg-white py-2 collapse-inner rounded'>"
                for sub_item in item['sub_menu']:
                    sub_menu_active = ''

                    if sub_item.get('type', '') == 'separator':
                        result += f"<h6 class='collapse-header'>" \
                        f"<span class='sr-only'>Separator</span>{sub_item['label']}</h6>"
                        continue

                    if sub_item['name'] == active_submenu:
                        sub_menu_active = 'active'   

                    if not sub_item.get('url', False):
                        continue
                    
                    try:
                        result += f"<a class='collapse-item {sub_menu_active}' href='"
                        if sub_item.get('url', False):
                            result += reverse(sub_item['url'])
                        result += f"'>{sub_item['label']}</a>"
                    except Exception as e:
                        print(e)


                result += "</div>"
                result += "</div>"
            result += "</li>\n\n"

    return result
