from django.apps import AppConfig


class CisConfig(AppConfig):
    name = 'cis'

    CONFIGURATORS = [
        {
            'app': 'cis',
            'name': 'syllabi_review',
            'title': 'Class Syllabi - Review',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'app': 'cis',
            'name': 'student_id_importer',
            'title': 'Student ID Importer',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        # {
        #     'app': 'cis',
        #     'name': 'recommendation_export',
        #     'title': 'Student Recommendation Export',
        #     'description': '-',
        #     'categories': [
        #         '1'
        #     ]
        # },
        {
            'name': 'menu',
            'title': 'System Menu',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'two_step',
            'title': 'Two Step Verification',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'sis_settings',
            'title': 'SIS GUIDS',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        # {
        #     'name': 'pending_class_syllabi',
        #     'title': 'Class Syllabi - Pending/Missing',
        #     'description': '-',
        #     'categories': [
        #         '3'
        #     ]
        # },
        {
            'name': 'password_reset',
            'title': 'Password Reset Email',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'future_sections',
            'title': 'Section Requests',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'class_section_importer',
            'title': 'Class Section Importer',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'student_exporter',
            'title': 'Student Exporter',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'registration_charges',
            'title': 'Registration Charges',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'support_docs',
            'title': 'Support Documents',
            'description': 'Student support-document types, statuses, and status-change email.',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'sms',
            'title': 'SMS',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'reports_email',
            'title': 'Report Ready Email Template',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'drop_wd_email',
            'title': 'Drop/WD Request Settings',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'roster_verification',
            'title': 'Roster Verification Settings',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'access_request',
            'title': 'Access Request Email Language',
            'description': '-',
            'categories': [
                '2'
            ]
        },
        {
            'name': 'highschool_admin_portal',
            'title': 'Portal - High School Admin Language',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'student_portal',
            'title': 'Portal - Student Pages',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'instructor_portal',
            'title': 'Portal - Instructor Pages',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'faculty_portal',
            'title': 'Portal - Faculty Pages',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        # {
        #     'name': 'pd_event',
        #     'title': 'PD Event Settings',
        #     'description': '-',
        #     'categories': [
        #         '4'
        #     ]
        # },
        {
            'name': 'incomplete_si_application',
            'title': 'Incomplete SI Application Email(s)',
            'description': '-',
            'categories': [
                '5'
            ]
        },
        {
            'name': 'teacher_certificate_renewal',
            'title': 'Instructor Credential Renewal Email(s)',
            'description': 'Reminder emails for instructors whose course certificates are expiring.',
            'categories': [
                '5'
            ]
        },
        {
            'name': 'teacher_application_email',
            'title': 'Instructor Application Email(s)',
            'description': '-',
            'categories': [
                '5'
            ]
        },
        {
            'name': 'inst_app_language',
            'title': 'Instructor Application Page',
            'description': '-',
            'categories': [
                '5'
            ]
        },
        {
            'name': 'portal_content',
            'title': 'Portal landing page Text',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'footer',
            'title': 'Footer Text',
            'description': '-',
            'categories': [
                '4'
            ]
        },
        {
            'name': 'registrations',
            'title': 'Registrations Open/Close',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'class_search',
            'title': 'Student Portal - Class Search Tab',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'counselor_recommendation',
            'title': 'Counselor - Recommendation Page Blurb',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        # {
        #     'name': 'drop_wd_req_email',
        #     'title': 'Drop Request Emails',
        #     'description': '-',
        #     'categories': [
        #         '1'
        #     ]
        # },
        {
            'name': 'ferpa',
            'title': 'Student Portal - FERPA Statement',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        # {
        #     'name': 'incomplete_student_app_reminder',
        #     'title': 'Incomplete Student App. Reminder Template',
        #     'description': '-',
        #     'categories': [
        #         '1'
        #     ]
        # },
        {
            'name': 'notes_email',
            'title': 'Class Notes Email Template',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        # {
        #     'name': 'parentconsent',
        #     'title': 'Parent Consent Page Template',
        #     'description': '-',
        #     'categories': [
        #         '1'
        #     ]
        # },
        {
            'name': 'registration_status_email',
            'title': 'Student Registration Change - SIS / Email Notifications',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'registration_email',
            'title': 'New Student Welcome Email / Parent Consent Email',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'school_counselor_regis_email',
            'title': 'Counselor - Student Recommendation Email Template',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'student_profile',
            'title': 'Student Portal - Profile Editing & Review',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'registration_profile',
            'title': 'Registration Detail Layout',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'class_section_profile',
            'title': 'Class Section Detail Layout',
            'description': '-',
            'categories': [
                '3'
            ]
        },
        {
            'name': 'signup',
            'title': 'Student Portal - New Student Signup Page Template',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'student_notes_email',
            'title': 'Student Notes Email Template',
            'description': '-',
            'categories': [
                '1'
            ]
        },
        {
            'name': 'student_regis_pending',
            'title': 'Incomplete Student Registration Notification',
            'description': '-',
            'categories': [
                '1'
            ]
        },
    ]

        
    REPORTS = [
        {
            'name': 'teacher_syllabi_status',
            'title': 'Teacher Syllabi Status - Export',
            'description': 'Per-section syllabus status (Submitted, Sent Back for Update, Approved, Not Submitted), filterable by term and status.',
            'categories': [
                'Instructors'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'teacher_password_reset',
            'title': 'Teacher Password Reset Export',
            'description': '-',
            'categories': [
                'High Schools'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'started_future_classes',
            'title': 'Started Future Classes Export',
            'description': '-',
            'categories': [
                'Classes'
            ],
            'available_for': [
                'ce'
            ]
        },
        # {
        #     'name': 'filled_form1098',
        #     'title': 'Tax Form 1098 Filled PDF Export',
        #     'description': '-',
        #     'categories': [
        #         'Students'
        #     ],
        #     'available_for': [
        #         'ce'
        #     ]
        # },
        # {
        #     'name': 'tax_form1098',
        #     'title': 'Tax Form 1098 Data Only Export',
        #     'description': '-',
        #     'categories': [
        #         'Students'
        #     ],
        #     'available_for': [
        #         'ce'
        #     ]
        # },
        {
            'name': 'duplicate_students',
            'title': 'Potential Duplicate Students Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'transactions',
            'title': 'Student Transactions Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'highschool_admin_missing_role',
            'title': 'High School Administrators Missing Role Export',
            'description': '-',
            'categories': [
                'High Schools'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'ferpa_export',
            'title': 'Student Ferpa Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'supporting_doc_export',
            'title': 'Supporting Documents Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'student_imaging_export',
            'title': 'Student Imaging Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'teacher_course_certificate',
            'title': 'Teacher Export',
            'description': '-',
            'categories': [
                'Instructors'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'teacher_certificates',
            'title': 'Teacher Course Certificates',
            'description': 'Teacher course certificates, optionally limited to those due within a given number of days, filterable by high school and status.',
            'categories': [
                'Instructors'
            ],
            'available_for': [
                'ce'
            ]
        },

        {
            'name': 'students_by_date',
            'title': 'Students By Date Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'student_profile_dynamic_export',
            'title': 'Student Profile Dynamic Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'drop_wd_requests',
            'title': 'Drop/WD Requests - Export',
            'description': '-',
            'categories': [
                'Classes'
            ],
            'available_for': [
                'ce'
            ]
        },
        # NOTE: future_classes, pending_future_classes, pending_future_classes_courses
        # reports moved to future_sections app
        {
            'name': 'class_export',
            'title': 'Class Details Export',
            'description': '-',
            'categories': [
                'Classes'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'detailed_students_with_class',
            'title': 'Detailed Students Export',
            'description': '-',
            'categories': [
                'Students'
            ],
            'available_for': [
                'ce'
            ]
        },
        # {
        #     'name': 'undup_students',
        #     'title': 'Students Export for Slate',
        #     'description': '-',
        #     'categories': [
        #         'Students'
        #     ],
        #     'available_for': [
        #         'ce'
        #     ]
        # },
        {
            'name': 'class_roster',
            'title': 'Class Roster Export',
            'description': '-',
            'categories': [
                'Classes'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'highschool_admin_export',
            'title': 'High School Administrator Export',
            'description': '-',
            'categories': [
                'High Schools'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'name': 'highschool_admin_password_reset',
            'title': 'School Administrator Password Link Export',
            'description': '-',
            'categories': [
                'High Schools'
            ],
            'available_for': [
                'ce'
            ]
        },
    ]

    def ready(self):
        import cis.checks  # noqa: F401  (registers system checks, e.g. STRIPE_WEBHOOK_SECRET)

        import cis.signals.students
        import cis.signals.registrations
        import cis.signals.notes
        import cis.signals.highschool_admin
        import cis.signals.teacher_applications
        import cis.signals.sections
        import cis.signals.support_docs

        import cis.signals.crontab

        from cis.signals import onboarding as onboarding_signals
        onboarding_signals.register_handlers()

        import cis.bmailer_datasources  # noqa: F401  (registers cis bulk-mailer datasources)

        self._bind_models_to_their_module()

        # Import every installed app's page_messages.py so @page_message
        # providers register. Missing modules are silently skipped; a module
        # with an internal import error still raises (fail loud).
        from django.utils.module_loading import autodiscover_modules
        autodiscover_modules('page_messages')

    def _bind_models_to_their_module(self):
        """
        Ensure every cis model is resolvable as an attribute of the module
        named by its ``__module__``.

        simple_history sets its ``Historical*`` models' ``__module__`` to
        the app import path (``cis``) instead of the submodule where the
        tracked model is defined (e.g. ``cis.models.student``), and binds
        the class only onto that submodule. Tools that resolve a model with
        ``getattr(import_module(model.__module__), model.__name__)`` — both
        Django's ``shell`` auto-import and ``django_admin_shell``'s
        ``get_scope`` — then raise ``AttributeError``. Bind the class onto
        that module so the lookup succeeds.
        """
        import importlib

        for model in self.get_models():
            module = importlib.import_module(model.__module__)
            if not hasattr(module, model.__name__):
                setattr(module, model.__name__, model)