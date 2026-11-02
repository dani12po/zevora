from enum import Enum


class Permission(str, Enum):
    ALLOW = 'allow'
    APPROVAL = 'approval'
    DENY = 'deny'


DEFAULTS = {
    'list_directory': Permission.ALLOW,
    'read_file': Permission.ALLOW,
    'search_files': Permission.ALLOW,
    'file_exists': Permission.ALLOW,
    'get_file_info': Permission.ALLOW,
    'project_index': Permission.ALLOW,
    'memory_search': Permission.ALLOW,
    'create_file': Permission.APPROVAL,
    'write_file': Permission.APPROVAL,
    'edit_file': Permission.APPROVAL,
    'delete_file': Permission.APPROVAL,
    'move_file': Permission.APPROVAL,
    'copy_file': Permission.APPROVAL,
    # Command approval is calculated from the command itself by the MCP gateway.
    'execute_command': Permission.ALLOW,
    'terminal': Permission.ALLOW,
    'git_push': Permission.APPROVAL,
    'package_install': Permission.APPROVAL,
}
