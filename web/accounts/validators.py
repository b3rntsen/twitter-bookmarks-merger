from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class NotAllLowercaseValidator:
    """
    Validate that the password is not composed entirely of lowercase letters.
    """

    def validate(self, password, user=None):
        if password.isalpha() and password.islower():
            raise ValidationError(
                _("Password cannot be only lowercase letters. "
                  "Add an uppercase letter, number, or special character."),
                code='all_lowercase',
            )

    def get_help_text(self):
        return _(
            "Your password cannot be only lowercase letters. "
            "Include at least one uppercase letter, number, or special character."
        )
