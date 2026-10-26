#pragma once
#include "3ds.h"
using FSPXI_Archive = u64;
using FSPXI_File = u64;
Result FSPXI_OpenArchive(Handle, FSPXI_Archive*, FS_ArchiveID, FS_Path);
Result FSPXI_OpenFile(Handle, FSPXI_File*, FSPXI_Archive, FS_Path, u32, u32);
Result FSPXI_GetFileSize(Handle, FSPXI_File, u64*);
Result FSPXI_ReadFile(Handle, FSPXI_File, u32*, u64, void*, u32);
Result FSPXI_CloseFile(Handle, FSPXI_File);
Result FSPXI_CloseArchive(Handle, FSPXI_Archive);
