REM This Source Code Form is subject to the terms of the Mozilla Public
REM License, v. 2.0. If a copy of the MPL was not distributed with this
REM file, You can obtain one at https://mozilla.org/MPL/2.0/.
REM
REM Page setup for AceOffice. LibreOfficeKit has no dialog-free command for page
REM margins, so AceOffice edits the current page style through these macros.
REM Lengths are in 1/100 mm; pass -1 to leave a value unchanged.

Function AcePageStyle() As Object
    Dim oDoc As Object, sName As String
    oDoc = ThisComponent
    If oDoc.supportsService("com.sun.star.sheet.SpreadsheetDocument") Then
        sName = oDoc.CurrentController.ActiveSheet.PageStyle
    Else
        sName = oDoc.CurrentController.ViewCursor.PageStyleName
    End If
    AcePageStyle = oDoc.StyleFamilies.getByName("PageStyles").getByName(sName)
End Function

Sub SetPage(nWidth As Long, nHeight As Long, nLandscape As Integer, nLeft As Long, nRight As Long, nTop As Long, nBottom As Long)
    Dim oStyle As Object
    oStyle = AcePageStyle()
    If nLandscape >= 0 Then oStyle.IsLandscape = (nLandscape = 1)
    If nWidth > 0 Then oStyle.Width = nWidth
    If nHeight > 0 Then oStyle.Height = nHeight
    If nLeft >= 0 Then oStyle.LeftMargin = nLeft
    If nRight >= 0 Then oStyle.RightMargin = nRight
    If nTop >= 0 Then oStyle.TopMargin = nTop
    If nBottom >= 0 Then oStyle.BottomMargin = nBottom
End Sub

Sub GetPage(sPath As String)
    Dim oStyle As Object, n As Integer
    oStyle = AcePageStyle()
    n = FreeFile()
    Open sPath For Output As #n
    Print #n, oStyle.Width & " " & oStyle.Height & " " & Abs(CInt(oStyle.IsLandscape)) & " " & _
              oStyle.LeftMargin & " " & oStyle.RightMargin & " " & oStyle.TopMargin & " " & oStyle.BottomMargin
    Close #n
End Sub
