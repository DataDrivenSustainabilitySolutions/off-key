import React from 'react';
//import { Routes, Route, Link } from 'react-router-dom';
//import { Button } from '@/components/ui/button';
import { NavigationBar } from "@/components/NavigationBar";
import { Hero } from "@/components/Hero";
import { FAQ } from "@/components/FAQ";
//import Login from '@/pages/Login.tsx';
//import Registration from '@/pages/Registration.tsx';

const Default: React.FC = () => {
  return (
    <>
      <NavigationBar />
      <Hero />
      <FAQ />
    </>
  );
};

export default Default;
