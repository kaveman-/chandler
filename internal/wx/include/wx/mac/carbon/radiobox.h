/////////////////////////////////////////////////////////////////////////////
// Name:        wx/mac/carbon/radiobox.h
// Purpose:     wxRadioBox class
// Author:      Stefan Csomor
// Modified by:
// Created:     1998-01-01
// RCS-ID:      $Id: radiobox.h,v 1.11 2006/03/24 22:50:45 ABX Exp $
// Copyright:   (c) Stefan Csomor
// Licence:     wxWindows licence
/////////////////////////////////////////////////////////////////////////////

#ifndef _WX_RADIOBOX_H_
#define _WX_RADIOBOX_H_

// List box item
class WXDLLEXPORT wxBitmap ;

class WXDLLEXPORT wxRadioButton ;

class WXDLLEXPORT wxRadioBox: public wxControl, public wxRadioBoxBase
{
    DECLARE_DYNAMIC_CLASS(wxRadioBox)
public:
// Constructors & destructor
    wxRadioBox();
    inline wxRadioBox(wxWindow *parent, wxWindowID id, const wxString& title,
             const wxPoint& pos = wxDefaultPosition, const wxSize& size = wxDefaultSize,
             int n = 0, const wxString choices[] = NULL,
             int majorDim = 0, long style = wxRA_HORIZONTAL,
             const wxValidator& val = wxDefaultValidator, const wxString& name = wxRadioBoxNameStr)
        {
            Create(parent, id, title, pos, size, n, choices, majorDim, style, val, name);
        }
    inline wxRadioBox(wxWindow *parent, wxWindowID id, const wxString& title,
             const wxPoint& pos, const wxSize& size,
             const wxArrayString& choices,
             int majorDim = 0, long style = wxRA_HORIZONTAL,
             const wxValidator& val = wxDefaultValidator,
             const wxString& name = wxRadioBoxNameStr)
     {
         Create(parent, id, title, pos, size, choices,
                majorDim, style, val, name);
     }
    ~wxRadioBox();
    bool Create(wxWindow *parent, wxWindowID id, const wxString& title,
             const wxPoint& pos = wxDefaultPosition, const wxSize& size = wxDefaultSize,
             int n = 0, const wxString choices[] = NULL,
             int majorDim = 0, long style = wxRA_HORIZONTAL,
             const wxValidator& val = wxDefaultValidator, const wxString& name = wxRadioBoxNameStr);
    bool Create(wxWindow *parent, wxWindowID id, const wxString& title,
             const wxPoint& pos, const wxSize& size,
             const wxArrayString& choices,
             int majorDim = 0, long style = wxRA_HORIZONTAL,
             const wxValidator& val = wxDefaultValidator,
             const wxString& name = wxRadioBoxNameStr);

    // Enabling
    virtual bool Enable(bool enable = true);
    virtual bool Enable(unsigned int item, bool enable = true);
    virtual bool IsItemEnabled(unsigned int WXUNUSED(n)) const
    {
        /* TODO */
        return true;
    }

    // Showing
    virtual bool Show(bool show = true);
    virtual bool Show(unsigned int item, bool show = true);
    virtual bool IsItemShown(unsigned int WXUNUSED(n)) const
    {
        /* TODO */
        return true;
    }

    // Specific functions (in wxWidgets2 reference)
    virtual void SetSelection(int item);
    virtual int GetSelection() const;

    virtual unsigned int GetCount() const { return m_noItems; }

    virtual wxString GetString(unsigned int item) const;
    virtual void SetString(unsigned int item, const wxString& label);

    virtual wxString GetLabel() const;
    virtual void SetLabel(const wxString& label) ;

// Other external functions
    void Command(wxCommandEvent& event);
    void SetFocus();

// Other variable access functions
    inline int GetNumberOfRowsOrCols() const { return m_noRowsOrCols; }
    inline void SetNumberOfRowsOrCols(int n) { m_noRowsOrCols = n; }

    void OnRadioButton( wxCommandEvent& event ) ;

protected:
    wxRadioButton    *m_radioButtonCycle;

    unsigned int      m_noItems;
    int               m_noRowsOrCols;

// Internal functions
    virtual wxSize DoGetBestSize() const ;
    virtual void DoSetSize(int x, int y,
                           int width, int height,
                           int sizeFlags = wxSIZE_AUTO);

    DECLARE_EVENT_TABLE()
};

#endif
    // _WX_RADIOBOX_H_
