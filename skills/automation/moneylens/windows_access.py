"""Owner-only Windows file ACLs, using the built-in Win32 security APIs.

No credential service is used. See Microsoft's Get/SetNamedSecurityInfoW docs.
Imported only on Windows; errors deliberately contain no file contents.
"""
import ctypes as c
from ctypes import wintypes as w


class WindowsAccess:
    def __init__(self):
        self.adv = c.WinDLL('advapi32', use_last_error=True)
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        ptr = c.c_void_p
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.LocalFree.argtypes = [ptr]
        self.kernel.LocalFree.restype = ptr
        signatures = {
            'OpenProcessToken': ([w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.BOOL),
            'GetTokenInformation': ([w.HANDLE, c.c_int, ptr, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
            'ConvertSidToStringSidW': ([ptr, c.POINTER(w.LPWSTR)], w.BOOL),
            'ConvertStringSecurityDescriptorToSecurityDescriptorW': ([w.LPCWSTR, w.DWORD, c.POINTER(ptr), ptr], w.BOOL),
            'GetNamedSecurityInfoW': ([w.LPWSTR, c.c_int, w.DWORD, c.POINTER(ptr), ptr, c.POINTER(ptr), ptr, c.POINTER(ptr)], w.DWORD),
            'SetNamedSecurityInfoW': ([w.LPWSTR, c.c_int, w.DWORD, ptr, ptr, ptr, ptr], w.DWORD),
            'GetSecurityDescriptorDacl': ([ptr, c.POINTER(w.BOOL), c.POINTER(ptr), c.POINTER(w.BOOL)], w.BOOL),
            'GetSecurityDescriptorControl': ([ptr, c.POINTER(w.WORD), c.POINTER(w.DWORD)], w.BOOL),
            'GetAce': ([ptr, w.DWORD, c.POINTER(ptr)], w.BOOL),
            'EqualSid': ([ptr, ptr], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.adv, name); fn.argtypes = args; fn.restype = result
        token, size = w.HANDLE(), w.DWORD()
        self.require(self.adv.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, c.byref(token)))
        try:
            self.adv.GetTokenInformation(token, 1, None, 0, c.byref(size))
            self.token_user = c.create_string_buffer(size.value)
            self.require(self.adv.GetTokenInformation(token, 1, self.token_user, size, c.byref(size)))
            self.adv.GetTokenInformation(token, 4, None, 0, c.byref(size))
            self.token_owner = c.create_string_buffer(size.value)
            self.require(self.adv.GetTokenInformation(token, 4, self.token_owner, size, c.byref(size)))
        finally:
            self.kernel.CloseHandle(token)
        self.sid = c.c_void_p.from_buffer(self.token_user).value
        self.default_owner = c.c_void_p.from_buffer(self.token_owner).value
        text = w.LPWSTR()
        self.require(self.adv.ConvertSidToStringSidW(self.sid, c.byref(text)))
        try: self.sid_text = text.value
        finally: self.kernel.LocalFree(c.cast(text, ptr))

    @staticmethod
    def require(ok):
        if not ok: raise ValueError('Cannot verify owner-only Windows file access')

    def inspect(self, path):
        owner, acl, descriptor = c.c_void_p(), c.c_void_p(), c.c_void_p()
        code = self.adv.GetNamedSecurityInfoW(str(path), 1, 5, c.byref(owner), None, c.byref(acl), None, c.byref(descriptor))
        self.require(code == 0)
        return owner, acl, descriptor

    def protect(self, path, directory=False):
        owner, _, previous = self.inspect(path)
        # Elevated Windows tokens may create files owned by their default
        # owner group. Normalize only that owner or the current user.
        try: self.require(self.adv.EqualSid(owner, self.sid) or self.adv.EqualSid(owner, self.default_owner))
        finally: self.kernel.LocalFree(previous)
        descriptor = c.c_void_p()
        # Protected DACL; only the current user can read/write. Directory ACEs
        # propagate to newly created children before their own ACL is checked.
        flags = 'OICI' if directory else ''
        sddl = 'D:P(A;' + flags + ';FA;;;' + self.sid_text + ')'
        self.require(self.adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(descriptor), None))
        try:
            present, defaulted, acl = w.BOOL(), w.BOOL(), c.c_void_p()
            self.require(self.adv.GetSecurityDescriptorDacl(descriptor, c.byref(present), c.byref(acl), c.byref(defaulted)))
            self.require(present.value and acl.value)
            self.require(self.adv.SetNamedSecurityInfoW(str(path), 1, 0x80000005, self.sid, None, acl, None) == 0)
        finally: self.kernel.LocalFree(descriptor)
        self.check(path)

    def check(self, path):
        owner, acl, descriptor = self.inspect(path)
        try:
            self.require(self.adv.EqualSid(owner, self.sid) and acl.value)
            control, revision = w.WORD(), w.DWORD()
            self.require(self.adv.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision)))
            self.require(control.value & 0x1000)  # SE_DACL_PROTECTED
            count = w.WORD.from_address(acl.value + 4).value
            self.require(count == 1)
            ace = c.c_void_p()
            self.require(self.adv.GetAce(acl, 0, c.byref(ace)))
            kind, flags = c.c_ubyte.from_address(ace.value).value, c.c_ubyte.from_address(ace.value + 1).value
            mask = w.DWORD.from_address(ace.value + 4).value
            self.require(kind == 0 and not flags & 0x10 and mask == 0x1f01ff)
            self.require(self.adv.EqualSid(ace.value + 8, self.sid))
        finally: self.kernel.LocalFree(descriptor)
