# cis/views/f1098.py

from pypdf import PdfReader, PdfWriter
from typing import Dict, List, Tuple, Optional
import traceback
import io


class Form1098TGenerator:
    """
    Generator for IRS Form 1098-T PDF documents.
    Handles validation and filling of 1098-T PDF templates.
    """
    
    # Define required fields for validation
    REQUIRED_FIELDS = [
        'filer_name',
        'filer_ein',
        'student_name',
        'student_tin',
        'student_address',
        'box1_payments',
        'box5_scholarships',
    ]
    
    # Map of optional field keys to actual PDF field names
    OPTIONAL_FIELD_MAPPING = {
        'filer_address': 'topmostSubform[0].CopyB[0].LeftCol[0].f2_7[0]',
        'box4_adjustments': 'topmostSubform[0].CopyB[0].RightCol[0].Box4_ReadOrder[0].f2_9[0]',
        'box6_scholarship_adjustments': 'topmostSubform[0].CopyB[0].RightCol[0].Box6_ReadOrder[0].f2_11[0]',
        'box10_insurance_refund': 'topmostSubform[0].CopyB[0].RightCol[0].f2_12[0]',
        'box7_jan_march_check': 'topmostSubform[0].CopyB[0].RightCol[0].c2_3[0]',
        'box8_halftime_check': 'topmostSubform[0].CopyB[0].RightCol[0].c2_4[0]',
        'box9_graduate_check': 'topmostSubform[0].CopyB[0].RightCol[0].c2_5[0]',
        'corrected_check': 'topmostSubform[0].CopyB[0].c2_1[0]',
    }
    
    def __init__(self, template_path: str):
        """
        Initialize the 1098-T generator with a template path.
        
        Args:
            template_path: Path to the fillable PDF template
        """
        self.template_path = template_path
    
    def validate_template(self) -> Tuple[bool, List[str], Dict[str, str]]:
        """
        Validate that the PDF template has all required 1098-T fields.
        
        Returns:
            Tuple of (is_valid, missing_fields, found_fields)
            - is_valid: True if all required fields exist
            - missing_fields: List of missing field names
            - found_fields: Dict of {field_name: field_type} for all fields found
        """
        try:
            reader = PdfReader(self.template_path)
            fields = reader.get_fields()
            
            if not fields:
                return False, self.REQUIRED_FIELDS, {}
            
            found_field_names = set(fields.keys())
            
            found_fields = {
                name: str(field.field_type) if hasattr(field, 'field_type') else 'unknown'
                for name, field in fields.items()
            }
            
            missing_fields = [
                field for field in self.REQUIRED_FIELDS 
                if field not in found_field_names
            ]
            
            is_valid = len(missing_fields) == 0
            
            return is_valid, missing_fields, found_fields
            
        except Exception as e:
            print(f"Error reading PDF: {e}")
            return False, self.REQUIRED_FIELDS, {}
    
    def print_validation_report(self):
        """
        Print a detailed validation report for the PDF template.
        """
        print(f"\n{'='*60}")
        print(f"1098-T Template Validation Report")
        print(f"{'='*60}")
        print(f"File: {self.template_path}\n")
        
        is_valid, missing_fields, found_fields = self.validate_template()
        
        if is_valid:
            print("✅ VALID - All required fields found!")
        else:
            print("❌ INVALID - Missing required fields:")
            for field in missing_fields:
                print(f"   - {field}")
        
        print(f"\nTotal fields found: {len(found_fields)}")
        print("\nAll fields in PDF:")
        for field_name, field_type in sorted(found_fields.items()):
            print(f"   {field_name}: {field_type}")
        
        print(f"{'='*60}\n")
    
    def generate_filled_form(
        self,
        filer_data: Dict[str, str],
        student_data: Dict[str, str],
        amounts: Dict[str, float],
        optional_amounts: Optional[Dict[str, float]] = None,
        checkboxes: Optional[Dict[str, bool]] = None
    ) -> io.BytesIO:
        """
        Generate a filled 1098-T PDF form and return as BytesIO object.
        
        Args:
            filer_data: Dict with keys: name, ein, address (optional)
            student_data: Dict with keys: name, tin, address, address2 (optional)
            amounts: Dict with keys: payments, scholarships
            optional_amounts: Optional dict with keys: adjustments, scholarship_adjustments, insurance_refund
            checkboxes: Optional dict with keys: jan_march, halftime, graduate, corrected
            
        Returns:
            BytesIO object containing the filled PDF
            
        Raises:
            Exception if PDF generation fails
        """
        try:
            reader = PdfReader(self.template_path)
            writer = PdfWriter()
            writer.append(reader)
            
            # Build the field data dictionary with required fields
            field_data = self._build_required_fields(filer_data, student_data, amounts)
            
            # Add optional student address line 2 if provided
            if student_data.get('address2'):
                field_data['student_address2'] = student_data['address2']
            
            # Add optional filer address if provided
            if filer_data.get('address'):
                field_data[self.OPTIONAL_FIELD_MAPPING['filer_address']] = filer_data['address']
            
            # Add optional amounts if provided
            if optional_amounts:
                self._add_optional_amounts(field_data, optional_amounts)
            
            # Add checkboxes if provided
            if checkboxes:
                self._add_checkboxes(field_data, checkboxes)
            
            # Fill the form fields
            writer.update_page_form_field_values(
                writer.pages[0],
                field_data,
                auto_regenerate=False
            )
            
            # Write to BytesIO instead of file
            pdf_bytes = io.BytesIO()
            writer.write(pdf_bytes)
            pdf_bytes.seek(0)  # Reset pointer to beginning
            
            return pdf_bytes
            
        except Exception as e:
            print(f"Error filling PDF: {e}")
            traceback.print_exc()
            raise
    
    def fill_pdf(
        self,
        output_path: str,
        filer_data: Dict[str, str],
        student_data: Dict[str, str],
        amounts: Dict[str, float],
        optional_amounts: Optional[Dict[str, float]] = None,
        checkboxes: Optional[Dict[str, bool]] = None
    ) -> bool:
        """
        Fill a 1098-T PDF template and save to disk.
        
        Args:
            output_path: Path where filled PDF should be saved
            filer_data: Dict with keys: name, ein, address (optional)
            student_data: Dict with keys: name, tin, address, address2 (optional)
            amounts: Dict with keys: payments, scholarships
            optional_amounts: Optional dict with keys: adjustments, scholarship_adjustments, insurance_refund
            checkboxes: Optional dict with keys: jan_march, halftime, graduate, corrected
            
        Returns:
            True if successful, False otherwise
        """
        try:
            pdf_bytes = self.generate_filled_form(
                filer_data=filer_data,
                student_data=student_data,
                amounts=amounts,
                optional_amounts=optional_amounts,
                checkboxes=checkboxes
            )
            
            # Write to file
            with open(output_path, 'wb') as f:
                f.write(pdf_bytes.getvalue())
            
            return True
            
        except Exception as e:
            print(f"Error saving PDF: {e}")
            traceback.print_exc()
            return False
    
    def _build_required_fields(
        self,
        filer_data: Dict[str, str],
        student_data: Dict[str, str],
        amounts: Dict[str, float]
    ) -> Dict[str, str]:
        """
        Build dictionary of required form fields.
        
        Args:
            filer_data: Filer information
            student_data: Student information
            amounts: Payment and scholarship amounts
            
        Returns:
            Dictionary of field names to values
        """
        return {
            # Filer information
            'filer_name': filer_data.get('name', ''),
            'filer_ein': filer_data.get('ein', ''),
            
            # Student information
            'student_name': student_data.get('name', ''),
            'student_tin': student_data.get('tin', ''),
            'student_address': student_data.get('address', ''),
            
            # Required amounts
            'box1_payments': self._format_currency(amounts.get('payments', 0.0)),
            'box5_scholarships': self._format_currency(amounts.get('scholarships', 0.0)),
        }
    
    def _add_optional_amounts(
        self,
        field_data: Dict[str, str],
        optional_amounts: Dict[str, float]
    ):
        """
        Add optional amount fields to field_data dictionary.
        
        Args:
            field_data: Dictionary to add fields to (modified in place)
            optional_amounts: Dictionary of optional amounts
        """
        if 'adjustments' in optional_amounts:
            field_data[self.OPTIONAL_FIELD_MAPPING['box4_adjustments']] = \
                self._format_currency(optional_amounts['adjustments'])
        
        if 'scholarship_adjustments' in optional_amounts:
            field_data[self.OPTIONAL_FIELD_MAPPING['box6_scholarship_adjustments']] = \
                self._format_currency(optional_amounts['scholarship_adjustments'])
        
        if 'insurance_refund' in optional_amounts:
            field_data[self.OPTIONAL_FIELD_MAPPING['box10_insurance_refund']] = \
                self._format_currency(optional_amounts['insurance_refund'])
    
    def _add_checkboxes(
        self,
        field_data: Dict[str, str],
        checkboxes: Dict[str, bool]
    ):
        """
        Add checkbox fields to field_data dictionary.
        
        Args:
            field_data: Dictionary to add fields to (modified in place)
            checkboxes: Dictionary of checkbox values
        """
        checkbox_mapping = {
            'jan_march': 'box7_jan_march_check',
            'halftime': 'box8_halftime_check',
            'graduate': 'box9_graduate_check',
            'corrected': 'corrected_check'
        }
        
        for key, mapping_key in checkbox_mapping.items():
            if key in checkboxes:
                field_data[self.OPTIONAL_FIELD_MAPPING[mapping_key]] = \
                    'Yes' if checkboxes[key] else 'Off'
    
    @staticmethod
    def _format_currency(amount: float) -> str:
        """
        Format a float amount as currency string.
        
        Args:
            amount: Amount to format
            
        Returns:
            Formatted currency string (e.g., "1234.56")
        """
        return f"{amount:.2f}"