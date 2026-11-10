REM This Source Code Form is subject to the terms of the Mozilla Public
REM License, v. 2.0. If a copy of the MPL was not distributed with this
REM file, You can obtain one at https://mozilla.org/MPL/2.0/.
REM
REM Presenter notes for AceOffice. LibreOfficeKit can only edit notes on LibreOffice's
REM own notes page, so AceOffice reads and writes them here. Text travels through
REM UTF-8 files (macro arguments can't carry line breaks or quotes safely).

Function AceNotesShape(nSlide As Long) As Object
    Dim oNotes As Object, i As Long
    oNotes = ThisComponent.DrawPages.getByIndex(nSlide).NotesPage
    For i = 0 To oNotes.Count - 1
        If oNotes.getByIndex(i).ShapeType = "com.sun.star.presentation.NotesShape" Then
            AceNotesShape = oNotes.getByIndex(i)
            Exit Function
        End If
    Next i
End Function

REM Write every slide's notes to sPath: one slide per record, records ended by a line
REM holding only the ASCII record separator (30).
Sub GetNotes(sPath As String)
    Dim oAccess As Object, oOut As Object, oText As Object, oShape As Object, n As Long, s As String
    oAccess = createUnoService("com.sun.star.ucb.SimpleFileAccess")
    If oAccess.exists(ConvertToURL(sPath)) Then oAccess.kill(ConvertToURL(sPath))
    oOut = oAccess.openFileWrite(ConvertToURL(sPath & ".part"))
    oText = createUnoService("com.sun.star.io.TextOutputStream")
    oText.setOutputStream(oOut)
    oText.setEncoding("UTF-8")
    For n = 0 To ThisComponent.DrawPages.Count - 1
        s = ""
        oShape = AceNotesShape(n)
        If Not IsNull(oShape) Then s = oShape.String
        oText.writeString(s & Chr(10) & Chr(30) & Chr(10))
    Next n
    oText.closeOutput()
    oAccess.move(ConvertToURL(sPath & ".part"), ConvertToURL(sPath))
End Sub

REM Set slide nSlide's notes to the contents of the UTF-8 file sPath. Call it with both
REM arguments quoted, SetNotes("3","/path"): a macro URL that mixes a bare number with a
REM string is rejected.
Sub SetNotes(nSlide As Long, sPath As String)
    Dim oAccess As Object, oIn As Object, oText As Object, oShape As Object, s As String
    oAccess = createUnoService("com.sun.star.ucb.SimpleFileAccess")
    oIn = oAccess.openFileRead(ConvertToURL(sPath))
    oText = createUnoService("com.sun.star.io.TextInputStream")
    oText.setInputStream(oIn)
    oText.setEncoding("UTF-8")
    s = ""
    Do While Not oText.isEOF()
        If s <> "" Then s = s & Chr(10)
        s = s & oText.readLine()
    Loop
    oText.closeInput()
    oShape = AceNotesShape(nSlide)
    If IsNull(oShape) Then
        REM A file without a notes placeholder: add one under the slide picture.
        Dim oNotes As Object, aSize As New com.sun.star.awt.Size, aPos As New com.sun.star.awt.Point
        oNotes = ThisComponent.DrawPages.getByIndex(nSlide).NotesPage
        oShape = ThisComponent.createInstance("com.sun.star.presentation.NotesShape")
        oNotes.add(oShape)
        aSize.Width = oNotes.Width * 0.8 : aSize.Height = oNotes.Height * 0.4
        aPos.X = oNotes.Width * 0.1 : aPos.Y = oNotes.Height * 0.5
        oShape.Size = aSize
        oShape.Position = aPos
    End If
    oShape.IsEmptyPresentationObject = False
    oShape.String = s
    If s = "" Then oShape.IsEmptyPresentationObject = True
    ThisComponent.setModified(True)
End Sub
