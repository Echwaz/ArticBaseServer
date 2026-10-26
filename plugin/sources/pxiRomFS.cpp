#include "pxiRomFS.hpp"
#include <3ds/services/fspxi.h>
#include <cstring>
extern "C" {
#include "csvc.h"
}

namespace ArticFunctions {
void ClosePxiProgramFile(PxiReadSession& session) {
    if (session.fileOpen) FSPXI_CloseFile(session.service, session.file);
    if (session.archiveOpen) FSPXI_CloseArchive(session.service, session.archive);
    if (session.service) svcCloseHandle(session.service);
    session = {};
}
Result OpenPxiProgramFile(PxiReadSession& session, u64 program, bool code) {
    ClosePxiProgramFile(session);
    Result res = svcControlService(SERVICEOP_STEAL_CLIENT_SESSION, &session.service, "PxiFS0");
    if (R_FAILED(res)) return res;
    res = FSPXI_OpenArchive(session.service, &session.archive, static_cast<FS_ArchiveID>(0x2345678E),
                           {PATH_BINARY, sizeof(program), &program});
    if (R_SUCCEEDED(res)) {
        session.archiveOpen = true;
        const u32 path[3] = {code ? 1u : 0u, code ? 0x646F632Eu : 0u, code ? 0x65u : 0u};
        res = FSPXI_OpenFile(session.service, &session.file, session.archive,
                            {PATH_BINARY, sizeof(path), path}, FS_OPEN_READ, 0);
        if (R_SUCCEEDED(res)) {
            session.fileOpen = true;
            res = FSPXI_GetFileSize(session.service, session.file, &session.size);
        }
    }
    if (R_FAILED(res)) ClosePxiProgramFile(session);
    return res;
}
Result ReadPxiProgramFile(PxiReadSession& session, u64 offset, u32 size, void* output, u32* read) {
    *read = 0;
    if (!session.fileOpen || offset > session.size || size > session.size - offset) {
        return static_cast<Result>(0xE0E046C1);
    }
    return FSPXI_ReadFile(session.service, session.file, read, offset, output, size);
}
Result ReadPxiHomeLayout(void* data, u32 size, u32* stage) {
    *stage = 1;
    if (size != 0x2558) return static_cast<Result>(0xE0E046C1);
    Handle service;
    Result res = svcControlService(SERVICEOP_STEAL_CLIENT_SESSION, &service, "PxiFS0");
    if (R_FAILED(res)) return res;
    const u32 path[] = {0, 0x20082};
    FSPXI_Archive archive;
    *stage = 2;
    res = FSPXI_OpenArchive(service, &archive, static_cast<FS_ArchiveID>(0x1234567C),
                            {PATH_BINARY, sizeof(path), path});
    if (R_SUCCEEDED(res)) {
        const char16_t name[] = u"/Launcher.dat";
        FSPXI_File file;
        *stage = 3;
        res = FSPXI_OpenFile(service, &file, archive,
                            {PATH_UTF16, sizeof(name), name}, FS_OPEN_READ, 0);
        if (R_SUCCEEDED(res)) {
            u64 actualSize = 0;
            *stage = 4;
            res = FSPXI_GetFileSize(service, file, &actualSize);
            if (R_SUCCEEDED(res) && actualSize != size) res = static_cast<Result>(0xE0E046C1);
            if (R_SUCCEEDED(res)) {
                u32 read = 0;
                *stage = 5;
                res = FSPXI_ReadFile(service, file, &read, 0, data, size);
                if (R_SUCCEEDED(res) && read != size) res = static_cast<Result>(0xE0E046C1);
            }
            const Result cleanup = FSPXI_CloseFile(service, file);
            if (R_SUCCEEDED(res)) res = cleanup;
        }
        const Result cleanup = FSPXI_CloseArchive(service, archive);
        if (R_SUCCEEDED(res)) res = cleanup;
    }
    svcCloseHandle(service);
    return res;
}
static void Probe(PxiRomFSReport* report, FS_ArchiveID id, FS_Path archivePath, FS_Path filePath) {
    *report = {};
    report->stage = 1;
    Handle service;
    report->result = svcControlService(SERVICEOP_STEAL_CLIENT_SESSION, &service, "PxiFS0");
    if (R_FAILED(report->result)) return;

    FSPXI_Archive archive;
    report->stage = 2;
    report->result = FSPXI_OpenArchive(service, &archive, id, archivePath);
    if (R_SUCCEEDED(report->result)) {
        FSPXI_File file;
        report->stage = 3;
        report->result = FSPXI_OpenFile(service, &file, archive,
            filePath, FS_OPEN_READ, 0);
        if (R_SUCCEEDED(report->result)) {
            report->stage = 4;
            report->result = FSPXI_GetFileSize(service, file, &report->size);
            if (R_SUCCEEDED(report->result) && report->size >= 0x200) {
                alignas(0x20) u8 header[0x200]{};
                report->stage = 5;
                report->result = FSPXI_ReadFile(service, file, &report->bytesRead,
                                               0, header, sizeof(header));
                if (R_SUCCEEDED(report->result) && report->bytesRead == sizeof(header)) {
                    std::memcpy(report->magic, header, sizeof(report->magic));
                }
            }
            report->fileClose = FSPXI_CloseFile(service, file);
        }
        report->archiveClose = FSPXI_CloseArchive(service, archive);
    }
    svcCloseHandle(service);
}
void ProbePxiRomFS(PxiRomFSReport* report) {
    const u32 titlePath[] = {0x00008202, 0x00040030, 0, 0};
    const u32 romfsPath[5]{};
    Probe(report, static_cast<FS_ArchiveID>(0x2345678A),
          {PATH_BINARY, sizeof(titlePath), titlePath},
          {PATH_BINARY, sizeof(romfsPath), romfsPath});
}
void ProbePxiProgramRomFS(PxiRomFSReport* report, u64 program) {
    const u32 romfsPath[3]{};
    Probe(report, static_cast<FS_ArchiveID>(0x2345678E),
          {PATH_BINARY, sizeof(program), &program},
          {PATH_BINARY, sizeof(romfsPath), romfsPath});
}
Result ReadPxiProgramRomFS(u64 program, u64 offset, u32 size, void* data,
                          u32* bytesRead, u64* fileSize) {
    *bytesRead = 0;
    *fileSize = 0;
    Handle service;
    Result res = svcControlService(SERVICEOP_STEAL_CLIENT_SESSION, &service, "PxiFS0");
    if (R_FAILED(res)) return res;
    FSPXI_Archive archive;
    res = FSPXI_OpenArchive(service, &archive, static_cast<FS_ArchiveID>(0x2345678E),
                            {PATH_BINARY, sizeof(program), &program});
    if (R_SUCCEEDED(res)) {
        const u32 path[3]{};
        FSPXI_File file;
        res = FSPXI_OpenFile(service, &file, archive,
                            {PATH_BINARY, sizeof(path), path}, FS_OPEN_READ, 0);
        if (R_SUCCEEDED(res)) {
            res = FSPXI_GetFileSize(service, file, fileSize);
            if (R_SUCCEEDED(res)) {
                if (offset > *fileSize || size > *fileSize - offset) {
                    res = static_cast<Result>(0xE0E046C1);
                } else {
                    res = FSPXI_ReadFile(service, file, bytesRead, offset, data, size);
                }
            }
            Result cleanup = FSPXI_CloseFile(service, file);
            if (R_SUCCEEDED(res)) res = cleanup;
        }
        Result cleanup = FSPXI_CloseArchive(service, archive);
        if (R_SUCCEEDED(res)) res = cleanup;
    }
    Result cleanup = svcCloseHandle(service);
    return R_FAILED(res) ? res : cleanup;
}
}
