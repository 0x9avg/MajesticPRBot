import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import ProtectedRoute from '../ProtectedRoute';

const renderWithRoutes = (initialPath: string, allowedRoles?: string[]) => {
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route path="/login" element={<div>Login Page</div>} />
                <Route path="/hub" element={<div>Hub Page</div>} />
                <Route element={<ProtectedRoute allowedRoles={allowedRoles} />}>
                    <Route path="/admin" element={<div>Admin Page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>
    );
};

describe('ProtectedRoute', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('redirects to login when token is missing', () => {
        renderWithRoutes('/admin');
        expect(screen.getByText('Login Page')).toBeInTheDocument();
    });

    it('allows access when token exists and role is allowed', () => {
        localStorage.setItem('access_token', 'token');
        localStorage.setItem(
            'user',
            JSON.stringify({ role: 'manager' })
        );

        renderWithRoutes('/admin', ['manager', 'developer']);
        expect(screen.getByText('Admin Page')).toBeInTheDocument();
    });

    it('redirects to hub when role is not allowed', () => {
        localStorage.setItem('access_token', 'token');
        localStorage.setItem(
            'user',
            JSON.stringify({ role: 'employee' })
        );

        renderWithRoutes('/admin', ['manager', 'developer']);
        expect(screen.getByText('Hub Page')).toBeInTheDocument();
    });

    it('redirects to login when role check is required but user payload is broken', () => {
        localStorage.setItem('access_token', 'token');
        localStorage.setItem('user', '{broken-json');

        renderWithRoutes('/admin', ['manager']);
        expect(screen.getByText('Login Page')).toBeInTheDocument();
    });
});
